# Insurance SOP Agent — 技术规格 v1.3

> 状态：设计冻结（2026-10-19）。
> v1.1 修正：O-3/S-10 无关问题只提议转人工；S-9/P-2 未询问邮件也可结束；M-5 明确各停止条件对应的级别。
> v1.3（实现期补充）：E-5 新增 `answer`/`asks_question`；`emotion.distress`；C-2 拒赔问题视为 status=denied；T-6 允许动作参数中的日期金额；F-10 主题映射；D-5 首次展示只给 net_pay；O-6 超岗位/非英文措辞；M-11 拒绝人工后回到 L2；H-4 转人工固定文案；§17 L3 场景脚本。
> v1.2 修正：S-11 与 S-4 的例外条件统一；G-4 区分纯函数 `policy.decide` 与编排函数 `handle_turn`；V-9 只对新的验证尝试计数；F-6 优先于 F-5；T-3/T-6/T-7 加强事实校验；P-5 邮件按事实条件渲染；P-7/P-8 明确邮件决定后的追问；Phase 枚举写成可运行代码。完整的讨论背景见 `docs/保险理赔SOP_Harness设计文档.docx`。
> 本文件是实现与测试的唯一依据。每条规则带编号，测试用例引用编号（例如 `# covers V-3`）。

---

## 0. 总原则

| ID | 规则 |
|---|---|
| G-1 | 阶段、权限、计数、跳转全部由 Python 决定；LLM 只输出**信号**（抽取）和**措辞**（生成）。 |
| G-2 | 信息隔离优于提示词约束：生成调用只能看到当前阶段允许的事实。 |
| G-3 | 每个动作都有固定兜底文案；LLM 不可用时流程仍能走完。 |
| G-4 | `policy.decide(state, ext, data, today) -> Step` 是**纯函数**：`data` 是作为参数传入的只读内存数据（及按 D-2 绑定的 `ClaimsRepo`）；不调用 LLM、没有 I/O、不修改输入，相同输入必得相同输出。`handle_turn(state, msg, llm, data, today) -> (next_state, reply)` 是有明确输入输出、可测试的**编排函数**（调用 LLM，有外部副作用）：开头 `next_state = state.model_copy(deep=True)`，之后只修改副本，不改动传入的 `state`。`today` 由入口传入。 |
| G-5 | 第一版只支持英文。 |

---

## 1. 数据层

| ID | 规则 |
|---|---|
| D-1 | `insurance_claims/fixtures/*.json`（路径由 `DATA_DIR` 配置）启动时加载为 Pydantic 只读模型（`frozen=True`，列表字段用 `tuple`）。不使用 SQLite。 |
| D-2 | `ClaimsRepo(db, authorized_party_id)` 只在验证/授权通过后创建；方法签名中**没有** `party_id` 参数；`get_claim` 对不属于本人的 case_id 返回 `None`。 |
| D-3 | `get_today()`：`DEMO_TODAY` 环境变量优先，否则 `date.today()`；只在入口调用。`.env.example` 默认 `DEMO_TODAY=2026-02-15`。 |
| D-4 | 文档名匹配：案件文档名的词集合 ⊆ 指南 key 的词集合即匹配；否则使用 `default_guidance`。 |
| D-5 | 金额解释必须附带 `claim_schema.json` 的字段定义。首次展示案件（PRESENT_CASE）只允许提及 `net_pay`；其余金额容易被误读为赔付额，只在追问时提供。 |

---

## 2. 状态机

```python
class Phase(str, Enum):
    VERIFY_ID = "VERIFY_ID"
    RESOLVE_INTENT = "RESOLVE_INTENT"
    PROCESS_CASE = "PROCESS_CASE"
    POST_PROCESS = "POST_PROCESS"
    COMPLETE = "COMPLETE"    # 终态
    HANDOFF = "HANDOFF"      # 终态
```

| ID | 从 | 条件 | 到 |
|---|---|---|---|
| S-1 | VERIFY_ID | 验证通过（V-1），代理人还需 consent=approved | RESOLVE_INTENT |
| S-2 | VERIFY_ID | `verify_failures == 3` 或 consent timeout | HANDOFF |
| S-3 | RESOLVE_INTENT | 案件已确定（C-规则） | PROCESS_CASE |
| S-4 | RESOLVE_INTENT | 名下无案件，或用户表示无须处理案件（没别的事）；不得绕过任何适用的安全门控 | POST_PROCESS |
| S-5 | PROCESS_CASE | `switch_case` | RESOLVE_INTENT |
| S-6 | PROCESS_CASE | `is_done` 或对 anything-else 回答否 | POST_PROCESS |
| S-7 | POST_PROCESS | 同一案件追问 → 停留，`pending_followup=True`；答完后按 P-8 决定是否重新询问邮件 | POST_PROCESS |
| S-8 | POST_PROCESS | 问另一个案件 | RESOLVE_INTENT |
| S-9 | POST_PROCESS | （`email_status ∈ {DECLINED, SENT}` **或** 本次不询问邮件，即 `discussed_facts` 为空、状态保持 NOT_OFFERED）且用户回应了 anything-else | COMPLETE |
| S-10 | 任意 | `wants_human` / 接受转人工提议 / 提议后第 4 次无关问题（O-3）/ 情绪阶梯 L4 / 验证后身份矛盾 | HANDOFF |
| S-11 | — | 禁止：从 VERIFY_ID 跳过身份验证进入任何后续阶段（VERIFY_ID 只能转到 RESOLVE_INTENT 或 HANDOFF）；验证后回到 VERIFY_ID；RESOLVE_INTENT 进入 POST_PROCESS 只允许 S-4 的情形；离开终态 | — |
| S-12 | — | 同一轮内最多连续推进 3 次转移，只生成一条回复 | — |

---

## 3. 每轮流程

```
copy state → extract (LLM, temp 0) → merge_memory → policy.decide 循环 (≤3) → tool gate
→ build_context → respond (LLM, temp 0.4) → fact checks (T-3/T-6) → output_guard → record facts
```

| ID | 规则 |
|---|---|
| T-1 | 抽取失败：带错误信息重试 1 次，仍失败 → `CLARIFY`，状态不变。 |
| T-2 | 生成失败 → 该动作的兜底文案。 |
| T-3 | 生成输出 `AgentReply{text, used_fact_ids}`。一条事实记入 `discussed_facts` 须同时满足：① 其 id 属于本轮 `must_state ∪ may_state`（不在其中的 id 直接丢弃）；② 该事实的关键词（case_id、文档名、日期、金额）出现在 `text` 中。关键词检查只证明“提到了”，不证明“说对了”；语义准确性由 L3 评测覆盖，并在 README 中说明。 |
| T-4 | `must_state` 中被漏讲的事实，用兜底句追加到回复末尾。 |
| T-5 | 每轮写入 `trace`：脱敏抽取结果、Directive、阶段转移、事实校验结果。 |
| T-6 | 数字与日期检查：回复中出现的每个金额和日期，都必须等于本轮允许事实或本轮动作参数（代码生成，如候选案件摘要）中的某个值（日期需识别多种写法）；不符 → 丢弃回复，改用该动作的兜底文案，并记入 trace。 |
| T-7 | T-4 兜底追加的句子由代码生成，其事实直接记入 `discussed_facts`，无需 T-3 校验。 |

---

## 4. 抽取结果（ExtractionResult）

```json
{
  "identity": {"full_name": null, "dob": null, "phone": null, "email": null,
               "id_last4": null, "id_type_stated": null},
  "policy_number": null,
  "caller_role": "unknown | policyholder | representative",
  "actor_name": null,
  "intent": "denial_question | status_inquiry | document_submission | next_steps | general_claim_question | null",
  "case_hint": {"case_id": null, "case_type": null, "status": null, "month": null, "year": null, "amount": null},
  "followup_topic": "submission_timing | processing_time | submission_method | file_format | receipt_confirmation | doc_alternatives | none",
  "emotion": {"type": "neutral | frustration | anger | anxiety | confusion", "intensity": 0, "abusive": false, "distress": false},
  "refusal": {"target": "none | field | verification | consent | email", "field": null},
  "off_topic": "none | out_of_role | unrelated | smalltalk | non_english",
  "wants_human": false, "is_done": false, "switch_case": false, "asks_to_skip": false,
  "asks_question": false, "answer": "none | yes | no",
  "email_decision": "none | yes | no | unclear",
  "corrections": []
}
```

| ID | 规则 |
|---|---|
| E-1 | LLM 只抽取原始值；归一化由 `normalize.py` 完成（DOB → ISO，电话 → E.164，姓名 → 小写去空格）。 |
| E-2 | 新值覆盖旧值，并追加 `Correction` 记录。 |
| E-3 | 任何阶段抽取到的意图/案件线索立即写入记忆，不改变 phase。 |
| E-4 | 验证前提出的案件问题写入 `pending_questions`，验证通过后主动回答。 |
| E-5 | `answer` 只表示对 agent 上一个是非问题的回答；如何解读由 `state.awaiting`（上一轮问的是什么）决定。`asks_question` 表示消息中含有关于理赔或流程的问题。 |

---

## 5. 身份验证

| ID | 规则 |
|---|---|
| V-1 | 通过条件：同一记录上 ≥3 项 PII 匹配 **且** 已提供字段无冲突 **且** 满足条件的记录恰好 1 条。PII = {full_name, dob, phone, email, id_last4}。 |
| V-2 | `policy_number` 只用于缩小候选，不计入 PII。 |
| V-3 | 姓名：忽略大小写/空格，查 `name_aliases`，允许顺序互换。 |
| V-4 | DOB、id_last4：归一化后精确比较。 |
| V-5 | 电话：E.164 精确比较，查 `phone_aliases`，**禁止模糊匹配**。 |
| V-6 | 邮箱：忽略大小写，查 `email_aliases`。 |
| V-7 | 用户声明的证件类型与记录 `id_type` 不符：该项既不算匹配也不算冲突。 |
| V-8 | 追问证件时使用中性说法（"SSN or national ID"）。 |
| V-9 | 只对**新的验证尝试**计数：对已提供字段计算指纹（字段名 + 归一化值）；仅当已提供 ≥3 项、且指纹与上次验证时不同（新增字段或更正）时才重新验证，未通过则 `verify_failures += 1`。重复同一组错误信息只计一次；不足 3 项不计。3 次 → HANDOFF。 |
| V-10 | 失败回复不得指出哪一项错，不得暗示账户存在。 |
| V-11 | 别名只来自数据文件。 |

---

## 6. 代理人与授权

| ID | 规则 |
|---|---|
| A-1 | 状态区分 `actor_type`、`actor_name`、`subject_party_id`、`consent_status`。 |
| A-2 | 代理人通过条件：`actor_name` 匹配 `representatives.json` 中该投保人的 rep 记录 + subject 的 3 项 PII 满足 V-1 + consent=approved。代理人自己的姓名不计入 subject 的 PII。 |
| A-3 | 授权序列来自 `consent_scenarios.json`，场景由 UI 选择；每检查一次前进一步；序列耗尽仍为 pending → timeout → HANDOFF。 |
| A-4 | 验证前改口为代理人：切换流程，保留已收集的 subject PII。验证后改口 → HANDOFF。 |
| A-5 | 验证后 `identity_locked=True`；询问他人案件（抽取信号 `about_other_person`）→ `OTHER_PERSON_LOCKED`：说明只能访问已验证投保人的案件，不切换、不查询。模型漏判时，由编排函数的关键词规则（“my son/wife… + claim/policy”）兜底。 |
| A-6 | 代理场景的邮件发送到投保人登记邮箱，并告知代理人。 |
| A-7 | 授权请求那一轮做第 1 次检查；之后每轮检查一次；序列最后一项仍为 pending 时即判定超时并转人工。代理人姓名缺失时先 `ASK_ACTOR_NAME`；姓名不在 rep 记录中 → 转人工。授权前 `subject_party_id` 为空，只记录 `pending_party_id`。 |

---

## 7. 案件匹配

| ID | 规则 |
|---|---|
| C-1 | 给出 case_id：在 `ClaimsRepo` 中精确查找；不属于本人 → "在您的账户下找不到"，不透露归属。 |
| C-2 | “足够明确” = case_type / status / 时间 / 金额 中至少 2 项，或有 case_id。`intent = denial_question` 且未给出 status 时，视为 status=denied（只算 1 项线索，单个候选时仍走 C-4 确认）。 |
| C-3 | 明确 + 唯一候选 → 直接处理，回复中点明案件编号和日期。 |
| C-4 | 模糊 + 唯一候选 → `CONFIRM_CASE`，带上候选摘要。 |
| C-5 | 多个候选 → `DISAMBIGUATE_CASE`；**最近年份只用于排序，不代替确认**。 |
| C-6 | 无候选 → `NO_MATCHING_CASE` 并列出名下案件；名下无案件 → `NO_CASES_ON_FILE`。 |
| C-7 | 相对时间（"last January"）按 `today` 解析，不能唯一确定时询问。 |
| C-8 | 验证前：不确认 case_id 是否存在；`ACK_HINT` 只复述用户原话。 |

---

## 8. 案件处理与 FAQ

| ID | 规则 |
|---|---|
| F-1 | `followup_topic` 由抽取层分类；代码取对应模板并填充 `{case_id}`、`{documents}`、`{average_processing_time_after_submission}`。 |
| F-2 | 同时附上相关文档指南（D-4）与 `case_type_guidance`。 |
| F-3 | LLM 可以改写措辞，不能增删事实。 |
| F-4 | 无匹配 topic → `claim_followup_fallback` + 提供转人工。 |
| F-5 | 截止日未过时："一周内提交"与 `appeal_deadline` 同时告知，截止日为硬性期限。 |
| F-6 | 截止日已过（`today > appeal_deadline`）：**优先于 F-5**，不使用 submission_timing 模板，不给出任何提交期限建议；如实说明截止日已过，不承诺申诉成功或延期，建议联系人工。 |
| F-7 | 记录中没有的信息 → `ANSWER_UNKNOWN`，不编造（含保障范围问题）。生成调用会收到 `CALLER_LATEST_MESSAGE`（已脱敏），须直接回答该问题、不重复已讲过的事实；事实无法回答时明确说无法从记录确认并提供人工。 |
| F-8 | 对非 denied 案件问拒赔原因 → 纠正状态。 |
| F-9 | 用户表示拿不到补件 → `OFFER_DOC_ALTERNATIVES`（`document_alternative_guidance`），用尽后指向人工审核。 |
| F-10 | 抽取层的 topic 名与 guideline 的 `topic` 键不同（`processing_time` → `processing_time_after_submission`，`file_format` → `file_format_requirements`），由 `guidance.TOPIC_KEYS` 映射；测试保证每个 topic 都有对应条目。 |

---

## 9. 范围控制

| ID | 规则 |
|---|---|
| O-1 | `unrelated`、`out_of_role` 计入 `off_topic_streak`；`smalltalk`、`non_english` 不计。 |
| O-2 | 消息中同时有正事 → 婉拒无关部分 + 正常处理，不计数。 |
| O-3 | streak == 3 → `OFFER_HANDOFF`（只提议，不转）。用户接受 → HANDOFF；回到正题 → streak 清零；提议后 streak == 4 → HANDOFF。 |
| O-4 | Prompt injection 视为 `unrelated`，阶段不变。 |
| O-5 | 一般保险名词可简短通用解释；schema 中有定义的字段用 schema 定义。 |
| O-6 | `out_of_role`：说明由其他团队处理、人工可转接；`non_english`：前置修饰 `ENGLISH_ONLY`（“目前只能用英文服务”），不计数。 |

---

## 10. 情绪与劝说

| ID | 规则 |
|---|---|
| M-1 | 情绪与拒绝是两个独立信号，同一次抽取调用输出。 |
| M-2 | 劝说阶梯 `escalation_level`：L1 ACK+EXPLAIN_GATE → L2 ACK+OFFER_ALT_FIELDS+轻提人工 → L3 OFFER_HANDOFF → L4 HANDOFF。 |
| M-3 | 升级触发：拒绝门控，或门控阶段情绪强度 ≥2。 |
| M-4 | 降级：本轮提供了新的有效字段 → 降一级，`no_progress_turns=0`。 |
| M-5 | 停止劝说：同一门控第 3 次拒绝 → L3，第 4 次 → L4；anger=3 连续 2 轮 → L3；辱骂第 1 次降温，第 2 次 → L4；`no_progress_turns == 4` → L3；明确要求人工 → L4；严重困扰 → L3（优先提供人工）。 |
| M-6 | 拒绝单个字段 → `OFFER_ALT_FIELDS`，不计入 `gate_refusals`。 |
| M-7 | `ACK_EMOTION` 只在情绪新出现或强度上升时使用。 |
| M-8 | 禁止：以部分信息让步、承诺结果、推卸责任、愧疚施压。 |
| M-9 | 门控理由由代码提供（见设计文档 13.6），LLM 只改写。 |
| M-10 | 所有阈值放在 `config.py`。 |
| M-11 | L3 提议人工后用户拒绝（且本轮没有再次拒绝验证）→ 回到 L2 继续验证。`anger_streak`（连续 anger=3 的轮数）与 `abuse_count` 由编排函数逐轮记账，规则判断仍在 policy 中。 |

---

## 11. POST_PROCESS 与邮件

| ID | 规则 |
|---|---|
| P-1 | `EmailStatus`: NOT_OFFERED → OFFERED → DECLINED / SENT。DECLINED 在 COMPLETE 前可改为同意；SENT 为终态，不重发不撤回。 |
| P-2 | 仅当 `discussed_facts` 非空时 `OFFER_EMAIL`；否则跳过邮件，`email_status` 保持 NOT_OFFERED，直接 `ASK_ANYTHING_ELSE`（满足 S-9）。HANDOFF 时不询问。 |
| P-3 | `unclear` → `RECONFIRM_EMAIL` 一次，不视为同意。 |
| P-4 | 只发登记邮箱，脱敏确认（`m*****@email.com`）；不接受新地址。 |
| P-5 | 邮件由确定性模板**按条件渲染**，内容只来自 `discussed_facts`：某一节没有对应事实时整节不出现。不含 PII 原值、情绪、内部推理。设计文档中的邮件示例是讨论过全部事实时的样子。 |
| P-6 | `EmailSender` 接口，只实现 `MockEmailSender`；UI 标注 "Mock outbox — not actually sent"。 |
| P-7 | SENT 之后：阶段仍为 POST_PROCESS，可继续回答同一案件的追问，并说明这部分不在已发送的邮件中；不重发。用户对 anything-else 回答没有了 → COMPLETE（S-9）。 |
| P-8 | 追问答完后是否再次询问邮件：`OFFERED` → 再询问一次；`DECLINED` → 不再主动询问（用户自己改主意仍可，见 P-1）；`SENT` → 不询问。 |

---

## 12. 转人工

| ID | 规则 |
|---|---|
| H-1 | `wants_human` → 立即 HANDOFF；VERIFY_ID 阶段附一句"人工仍会核实身份"。 |
| H-2 | `HandoffRecord` = `internal_summary` + `user_message`（含参考号 H-xxxx）。 |
| H-3 | 内部摘要：原因、情绪、用户自述诉求、已提供哪些身份字段（不含值）、失败次数；已验证才含案件信息。 |
| H-4 | 含 `HANDOFF` 的回合不调用生成 LLM，使用固定文案（含参考号；未验证时提示人工仍会核实身份）。 |

---

## 13. 隐私与安全

| ID | 规则 |
|---|---|
| X-1 | `history` 在抽取后脱敏存储：`[NAME] [DOB] [ID_LAST4] [PHONE] [EMAIL]`。 |
| X-2 | 生成调用：验证前无任何 PII；验证后只有 `display_name`。 |
| X-3 | debug 面板与日志一律脱敏显示。 |
| X-4 | Output guard（报警器）：验证前回复命中案件敏感值黑名单 → 改用兜底文案并记录；任何阶段不出现完整 DOB/证件号/电话。测试断言其从未触发。 |
| X-5 | API key 只存 `st.session_state`；不入 URL、日志、trace；异常信息包装后显示。 |
| X-6 | `@st.cache_resource` 只缓存只读数据仓库；LLM client 按会话创建。 |

---

## 14. SessionState

```python
class SessionState(BaseModel):
    phase: Phase = Phase.VERIFY_ID
    turn: int = 0
    # identity
    actor_type: Literal["policyholder", "representative"] = "policyholder"
    actor_name: str | None = None
    identity_claims: dict[str, ClaimedField] = {}
    corrections: list[Correction] = []
    subject_party_id: str | None = None
    identity_locked: bool = False
    consent_status: Literal["not_required", "pending", "approved", "timeout"] = "not_required"
    consent_checks: int = 0
    # counters
    verify_failures: int = 0
    gate_refusals: dict[str, int] = {}
    no_progress_turns: int = 0
    off_topic_streak: int = 0
    escalation_level: int = 0
    last_emotion: EmotionSignal | None = None
    # memory
    intent: Intent | None = None
    case_query: CaseQuery = CaseQuery()
    pending_questions: list[str] = []
    resolved_case_id: str | None = None
    # wrap-up
    discussed_facts: list[Fact] = []
    pending_followup: bool = False
    email_status: EmailStatus = EmailStatus.NOT_OFFERED
    handoff: HandoffRecord | None = None
    # conversation
    history: list[Turn] = []
    trace: list[TurnTrace] = []
```

---

## 15. 动作集合

| 阶段 | 动作 |
|---|---|
| VERIFY_ID | `ASK_ID` `ID_MISMATCH` `EXPLAIN_GATE` `OFFER_ALT_FIELDS` `VERIFIED` `REQUEST_CONSENT` `CONSENT_PENDING` |
| RESOLVE_INTENT | `ASK_INTENT` `CONFIRM_CASE` `DISAMBIGUATE_CASE` `NO_MATCHING_CASE` `NO_CASES_ON_FILE` `CASE_RESOLVED` |
| PROCESS_CASE | `PRESENT_CASE` `ANSWER_FOLLOWUP` `ANSWER_UNKNOWN` `OFFER_DOC_ALTERNATIVES` `ASK_ANYTHING_ELSE` |
| POST_PROCESS | `OFFER_EMAIL` `RECONFIRM_EMAIL` `EMAIL_SENT` `EMAIL_SKIPPED` `CLOSE` |
| 全局 | `DEFLECT_OFF_TOPIC` `OFFER_HANDOFF` `HANDOFF` `CLARIFY` `TRANSITION`（内部：只切换阶段，不产生文字） |
| 前置修饰 | `ACK_EMOTION` `ACK_HINT` `DEFLECT` `SMALLTALK` |

优先级：安全拦截 > 转人工 > 阶段主动作；情绪与无关问题只作为前置修饰。

---

## 16. 配置

| 变量 | 默认 | 说明 |
|---|---|---|
| `OPENAI_API_KEY` | — | 也可在 UI 中输入 |
| `OPENAI_BASE_URL` | OpenAI 官方 | 兼容接口 |
| `EXTRACT_MODEL` / `RESPONSE_MODEL` | 同一模型 | |
| `DEMO_TODAY` | `2026-02-15` | 未设置则用真实日期 |
| `DATA_DIR` | `insurance_claims/fixtures` | fixture 所在目录，直接使用原始数据，不复制 |
| 阈值 | verify 3 / off-topic 3 / refusals 3 / no-progress 4 / anger 2 轮 | `config.py` |

---

## 17. 验收

- 标准用例（Margaret）一轮内：验证通过 → 定位 CL-2048 → 讲解拒赔原因与补件 → 后续询问邮件。
- 设计文档第 19 章所有 P0 场景通过（L2 用 FakeLLM，L3 用真实 LLM）。
- X-4 输出检查在全部测试中从未触发。
- Docker 一条命令可启动；UI 可输入 API key；Harness trace 可见。
- L3：`OPENAI_API_KEY=... .venv/bin/python scripts/run_scenarios.py [--report docs/scenario-report.md]` 跑 `tests/scenarios.yaml` 全部场景；先做一次预检，key/URL/模型有误时直接退出。

## 18. 排期（48h）

| 时间 | 范围 |
|---|---|
| 0–16h | P0：数据层、V/C 规则、状态机、Directive + 兜底文案、两次 LLM 调用、基础 UI、Docker |
| 16–32h | P1：O/M/F/P 规则、Harness trace、L1/L2 测试 |
| 32–42h | P2：A 规则（先 default）、快速场景按钮、托管部署 |
| 42–48h | README（Design Decisions）、演示、缓冲 |

删减顺序：L3 评测 → consent timeout → 快速场景按钮。Harness trace 与 README 不删。
