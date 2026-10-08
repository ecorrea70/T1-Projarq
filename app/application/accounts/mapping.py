"""Identidade, validação e mapeamento dos cadastros para contas Moodle."""
from email_validator import EmailNotValidError, validate_email


def map_identity(person, kind="students"):
    label = "aluno" if kind == "students" else "professor"
    code = person.get(f"{label}_id")
    if isinstance(code, bool) or not isinstance(code, int) or code < 0:
        raise ValueError(f"Código do {label} inválido.")
    return {"username": f"ieducar-{label}-{code}", "idnumber": f"ieducar:{label}:{code}"}


def map_user(person, kind="students"):
    identity = map_identity(person, kind)
    name = " ".join(str(person.get("nome") or "").split())
    parts = name.rsplit(" ", 1)
    if not name:
        raise ValueError("Cadastro sem nome.")
    if len(parts) == 1:
        parts.append("-")  # Campo obrigatório no Moodle; não inventa sobrenome.
    if any(len(part) > 100 for part in parts):
        raise ValueError("Nome e sobrenome devem ter até 100 caracteres cada.")
    try:
        email = validate_email(str(person.get("email") or "").strip(), check_deliverability=False).normalized
        if len(email) > 100:
            raise ValueError("E-mail excede o limite do Moodle.")
    except EmailNotValidError:
        raise ValueError("Cadastro sem e-mail válido.") from None
    return {**identity,
            "firstname": parts[0], "lastname": parts[1], "email": email}
