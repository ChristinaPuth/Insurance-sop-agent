"""Fixed text for every action (SPEC G-3). Used when the LLM is unavailable or its reply is rejected."""
from __future__ import annotations

from .schemas import Action, Directive, Preface, Step

GREETING = ("Hi, thanks for contacting claims support. Before I can look at any claim, I need to verify "
            "your identity. Please share at least three of the following: your full name, date of birth, "
            "phone number, email on file, or the last 4 digits of your SSN or national ID.")

CONFIG_ERROR = ("[Setup problem] The AI service rejected the request. Check the API key, Base URL and model "
                "in the sidebar, then send your message again.")

BUSY = "Sorry, our system is busy right now. Please send your last message again in a moment."

FIELD_LABELS = {
    "full_name": "your full name",
    "dob": "your date of birth",
    "phone": "the phone number on file",
    "email": "the email on file",
    "id_last4": "the last 4 digits of your SSN or national ID",
}

GATE_REASON = ("Your claim file contains medical and payment details, so I need to confirm it's really you "
               "before I can open it. This protects you from someone else accessing your information.")


def _fields(names: list[str]) -> str:
    labels = [FIELD_LABELS[n] for n in names]
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + ", or " + labels[-1]


def _step_text(step: Step) -> str:
    a, p = step.action, step.params
    if a == Action.ASK_ID:
        n = p.get("needed", 3)
        item = "item" if n == 1 else "items"
        return f"To verify your identity I need {n} more {item}. You can use any of: {_fields(p['missing'])}."
    if a == Action.ID_MISMATCH:
        return ("I couldn't verify the information provided. You can try again with your details or use "
                f"another accepted verification field: {_fields(p['options'])}.")
    if a == Action.EXPLAIN_GATE:
        return GATE_REASON + " " + _step_text(Step(action=Action.ASK_ID, params=p))
    if a == Action.OFFER_ALT_FIELDS:
        extra = " If you'd rather not, I can also connect you with a representative." if p.get("mention_handoff") else ""
        return f"That's completely fine — you can use {_fields(p['options'])} instead.{extra}"
    if a == Action.VERIFIED:
        if p.get("representative"):
            return "Thank you — the policyholder has approved the request, so I can help you with their claims now."
        return "Thank you, you're verified."
    if a == Action.ASK_ACTOR_NAME:
        return ("Thank you. Since you're calling on the policyholder's behalf, could you tell me your own full "
                "name?")
    if a == Action.ASK_INTENT:
        return "How can I help you with your claim today?"
    if a == Action.CONFIRM_CASE:
        return f"I see one matching claim on your account: {p['summary']} Is that the one you're calling about?"
    if a == Action.DISAMBIGUATE_CASE:
        return "I found more than one matching claim: " + "; ".join(p["summaries"]) + ". Which one would you like to discuss?"
    if a == Action.NO_MATCHING_CASE:
        lead = (f"I can't find claim {p['unknown_case_id']} on your account."
                if p.get("unknown_case_id") else "I couldn't find a claim matching that description on your account.")
        return lead + " The claims on your account are: " + "; ".join(p["summaries"]) + ". Which one can I help with?"
    if a == Action.NO_CASES_ON_FILE:
        return "I don't see any claims on your account."
    if a == Action.PRESENT_CASE:
        return "Do you have any questions about this claim?"
    if a == Action.ANSWER_FOLLOWUP:
        note = (" This part isn't included in the summary email I already sent."
                if p.get("after_email_sent") else "")
        if p.get("topic", "none") == "none":
            return ("I can't confirm that from the records I have — I can only answer from the details on your "
                    "claim file. A representative can look into it if you'd like." + note)
        return note.strip()
    if a in (Action.CASE_RESOLVED, Action.TRANSITION):
        return ""            # facts carry the content
    if a == Action.ANSWER_UNKNOWN:
        return "I'm not able to confirm that from the records I have. A representative can look into it if you'd like."
    if a == Action.ASK_ANYTHING_ELSE:
        return "Is there anything else I can help you with?"
    if a == Action.OFFER_EMAIL:
        whose = "the policyholder's email on file" if p.get("to_policyholder") else "the address on file"
        return f"Would you like me to email a summary of this conversation to {whose} ({p['email_masked']})?"
    if a == Action.RECONFIRM_EMAIL:
        return "Just to confirm — should I send the summary email, yes or no?"
    if a == Action.EMAIL_SENT:
        note = " It covers what we discussed up to now." if p.get("note_followups") else ""
        return f"Done — I've sent the summary to {p['email_masked']}.{note}"
    if a == Action.EMAIL_SKIPPED:
        return "No problem, I won't send an email."
    if a == Action.CLOSE:
        return "Thank you for contacting claims support. Take care!"
    if a == Action.DEFLECT_OFF_TOPIC:
        nudge = ("Whenever you're ready, I can continue verifying your identity." if p.get("nudge") == "verify"
                 else "Is there anything about your claim I can help with?")
        if p.get("kind") == "out_of_role":
            return ("That's handled by another team — I can only help with insurance claims here, but a "
                    f"representative can point you to the right department. {nudge}")
        return f"I'm sorry, I can only help with insurance claim questions here. {nudge}"
    if a == Action.OFFER_HANDOFF:
        if p.get("gate"):
            return ("I can't share claim details without verification — that's to protect you. Would you like to "
                    "continue with the remaining items, or should I connect you with a representative?")
        return "It seems I may not be the best help for this. Would you like me to connect you with a representative?"
    if a == Action.HANDOFF:
        extra = " The representative will still need to verify your identity." if p.get("unverified") else ""
        return f"I'm transferring you to a representative now. Your reference number is {p['reference']}.{extra}"
    if a == Action.OTHER_PERSON_LOCKED:
        return ("I can only access claims associated with the verified policyholder in this session. To discuss "
                "another person's claim, that person would need to complete their own verification or authorize "
                "you. Is there anything else I can help with on your own claims?")
    if a == Action.CLARIFY:
        return "Sorry, I didn't quite catch that. Could you rephrase?"
    if a == Action.REQUEST_CONSENT:
        return p["reason"] + " Let me know once they've approved it."
    if a == Action.CONSENT_PENDING:
        return ("The authorization is still pending. I can't share any claim details until the policyholder "
                "approves — this protects their health information. Let me know once they've approved it.")
    if a == Action.OFFER_DOC_ALTERNATIVES:
        return ""
    return ""


def _preface_text(pref: Preface, params: dict) -> str:
    if pref == Preface.ACK_EMOTION:
        return "I understand this is frustrating, and I'm sorry for the trouble."
    if pref == Preface.ACK_HINT:
        return f"I've noted that you're calling about {params['hint_text']}."
    if pref == Preface.DEFLECT:
        return "I can only help with insurance claim questions, so I'll set that part aside."
    if pref == Preface.THANKS:
        return "Thank you."
    if pref == Preface.ENGLISH_ONLY:
        return "I'm sorry, I can currently only assist in English."
    return ""


def render(directive: Directive) -> str:
    parts = [_preface_text(p, directive.preface_params) for p in directive.prefaces]
    facts_done = False
    for step in directive.steps:
        if step.action in (Action.PRESENT_CASE, Action.ANSWER_FOLLOWUP) and not facts_done:
            parts.extend(f.value for f in directive.must_state)
            facts_done = True
        parts.append(_step_text(step))
    return " ".join(p for p in parts if p).strip()
