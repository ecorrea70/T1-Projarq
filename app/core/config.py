import os
from dataclasses import dataclass
from urllib.parse import urlsplit


class ConfigurationError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    ieducar_url: str
    ieducar_token: str
    moodle_url: str
    moodle_token: str
    timeout: int = 15
    ieducar_access_key: str = ""
    institution_id: str = ""
    school_id: str = ""
    year: str = ""
    moodle_category_id: int = 0
    moodle_teacher_role_id: int = 0
    moodle_student_role_id: int = 0

    @classmethod
    def from_env(cls, kind="students"):
        required = ["IEDUCAR_URL", "MOODLE_URL", "MOODLE_TOKEN"]
        if kind == "teachers":
            required += ["IEDUCAR_ACCESS_KEY", "IEDUCAR_INSTITUTION_ID", "IEDUCAR_SCHOOL_ID", "IEDUCAR_YEAR"]
            required += ["MOODLE_CATEGORY_ID", "MOODLE_TEACHER_ROLE_ID"]
        else:
            required += ["IEDUCAR_TOKEN", "IEDUCAR_ACCESS_KEY", "IEDUCAR_INSTITUTION_ID", "IEDUCAR_SCHOOL_ID",
                         "IEDUCAR_YEAR", "MOODLE_STUDENT_ROLE_ID"]
        missing = [name for name in required if not os.getenv(name, "").strip()]
        if missing:
            raise ConfigurationError("Configure: " + ", ".join(missing))
        try:
            timeout = int(os.getenv("HTTP_TIMEOUT", "15"))
            if not 1 <= timeout <= 120:
                raise ValueError
            urls = [os.environ[name].rstrip("/") for name in ("IEDUCAR_URL", "MOODLE_URL")]
            for url in urls:
                parsed = urlsplit(url)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.query or parsed.fragment or parsed.username:
                    raise ValueError
            scope = [os.getenv(name, "").strip() for name in
                     ("IEDUCAR_INSTITUTION_ID", "IEDUCAR_SCHOOL_ID", "IEDUCAR_YEAR")]
            numeric = [scope[0], scope[2], *scope[1].split(",")]
            if any(value and (not value.isascii() or not value.isdecimal() or int(value) < 1) for value in numeric):
                raise ValueError
            if scope[1] and any(not value for value in scope[1].split(",")):
                raise ValueError
            teaching_ids = [int(os.getenv(name, "0") or "0") for name in ("MOODLE_CATEGORY_ID", "MOODLE_TEACHER_ROLE_ID")]
            student_role = int(os.getenv("MOODLE_STUDENT_ROLE_ID", "0") or "0")
            if kind == "teachers" and any(value < 1 for value in teaching_ids):
                raise ValueError
            if kind == "students" and student_role < 1:
                raise ValueError
        except ValueError:
            raise ConfigurationError("URL, escopo, IDs do Moodle ou timeout inválido.") from None
        return cls(urls[0], os.getenv("IEDUCAR_TOKEN", ""), urls[1], os.environ["MOODLE_TOKEN"],
                   timeout, os.getenv("IEDUCAR_ACCESS_KEY", ""), *scope, *teaching_ids, student_role)
