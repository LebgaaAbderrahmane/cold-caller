SYSTEM_PROMPT_TEMPLATE = """You are a cold caller for {company_name}.
Your value proposition: {value_prop}
Your objective: {call_objective}

Rules:
- Be natural and conversational, NOT robotic.
- Speak in {language}.
- Keep responses under 20 words.
- Do NOT identify yourself as AI unless directly asked.
- If prospect says "not interested" or asks to stop, acknowledge politely and close.
- If prospect asks to call later, ask for a specific time and confirm.
- After achieving the objective, close naturally.
- Never make up information.
- Output ONLY your spoken response. No stage directions, no explanations.

Call context:
- Prospect name: {prospect_name}
- Company: {prospect_company}

Conversation history:
{conversation_history}

Generate ONLY your next spoken response:"""


GREETING_TEMPLATES = {
    "en": "Hello {name}, this is {agent_name} from {company}. I'm calling because {value_prop} — do you have a moment to talk?",
    "fr": "Bonjour {name}, ici {agent_name} de {company}. Je vous appelle parce que {value_prop} — avez-vous un moment ?",
    "ar": "السلام عليكم {name}، هذا {agent_name} من {company}. أتصل بك لأن {value_prop} — هل لديك دقيقة؟",
}

CLOSING_TEMPLATES = {
    "en": "Thank you for your time, {name}. Have a great day!",
    "fr": "Merci pour votre temps, {name}. Bonne journée !",
    "ar": "شكرًا لك على وقتك {name}. يوم سعيد!",
}


def format_conversation(history: list[tuple[str, str]]) -> str:
    lines = []
    for speaker, text in history:
        label = "Assistant" if speaker == "assistant" else "Prospect"
        lines.append(f"{label}: {text}")
    return "\n".join(lines) if lines else "(no conversation yet)"


def build_system_prompt(
    company_name: str,
    value_prop: str,
    call_objective: str,
    language: str,
    prospect_name: str,
    prospect_company: str,
    conversation_history: list[tuple[str, str]],
) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(
        company_name=company_name,
        value_prop=value_prop,
        call_objective=call_objective,
        language=language,
        prospect_name=prospect_name or "there",
        prospect_company=prospect_company or "your company",
        conversation_history=format_conversation(conversation_history),
    )


def build_greeting(
    name: str, agent_name: str, company: str, value_prop: str, language: str = "en"
) -> str:
    template = GREETING_TEMPLATES.get(language, GREETING_TEMPLATES["en"])
    return template.format(
        name=name, agent_name=agent_name, company=company, value_prop=value_prop
    )


def build_closing(name: str, language: str = "en") -> str:
    template = CLOSING_TEMPLATES.get(language, CLOSING_TEMPLATES["en"])
    return template.format(name=name)
