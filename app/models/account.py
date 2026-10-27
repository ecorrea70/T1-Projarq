"""Modelos de identidade e mapeamento de contas de alunos e professores."""
from dataclasses import dataclass
from email_validator import EmailNotValidError, validate_email


@dataclass(frozen=True)
class AccountIdentity:
    """Representa a identidade única de um usuário sincronizado no Moodle."""
    username: str
    idnumber: str

    def to_dict(self) -> dict[str, str]:
        return {"username": self.username, "idnumber": self.idnumber}


@dataclass(frozen=True)
class UserAccountModel:
    """Representa os dados de conta validados para criação no Moodle."""
    username: str
    idnumber: str
    firstname: str
    lastname: str
    email: str

    def to_dict(self) -> dict[str, str]:
        return {
            "username": self.username,
            "idnumber": self.idnumber,
            "firstname": self.firstname,
            "lastname": self.lastname,
            "email": self.email,
        }


def build_account_identity(person: dict, kind: str = "students") -> AccountIdentity:
    label = "aluno" if kind == "students" else "professor"
    code = person.get(f"{label}_id")
    if isinstance(code, bool) or not isinstance(code, int) or code < 0:
        raise ValueError(f"Código do {label} inválido.")
    return AccountIdentity(
        username=f"ieducar-{label}-{code}",
        idnumber=f"ieducar:{label}:{code}",
    )


def build_user_account(person: dict, kind: str = "students") -> UserAccountModel:
    identity = build_account_identity(person, kind)
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
    return UserAccountModel(
        username=identity.username,
        idnumber=identity.idnumber,
        firstname=parts[0],
        lastname=parts[1],
        email=email,
    )


def map_identity(person: dict, kind: str = "students") -> dict[str, str]:
    return build_account_identity(person, kind).to_dict()


def map_user(person: dict, kind: str = "students") -> dict[str, str]:
    return build_user_account(person, kind).to_dict()
