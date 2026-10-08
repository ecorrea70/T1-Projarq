# T1 — Integração i-Educar × Moodle

Monolito que sincroniza alunos, professores, cursos e matrículas pelas APIs.
Todo o ambiente é executado com Docker Compose, sem depender de pastas irmãs.
O i-Educar é um submodule em `services/i-educar`; o Moodle usa uma imagem Docker.

## Preparação

Pré-requisitos: Git e Docker com Compose.

```bash
git clone --recurse-submodules https://github.com/ecorrea70/T1-Projarq.git
cd T1-Projarq
```

Se já clonou, execute `git submodule update --init --recursive`.

Somente na primeira configuração, copie os exemplos:

```bash
cp .env.example .env
cp services/i-educar/.env.example services/i-educar/.env
```

Não sobrescreva arquivos `.env` existentes. No `.env` do monolito, preencha:

- Senhas: `IEDUCAR_DB_PASSWORD`, `MOODLE_DB_PASSWORD` e `MOODLE_ADMIN_PASSWORD`.
- Credenciais: `IEDUCAR_TOKEN`, `IEDUCAR_ACCESS_KEY`, `MOODLE_TOKEN` e `SYNC_API_TOKEN`.
- Escopo: `IEDUCAR_INSTITUTION_ID`, `IEDUCAR_SCHOOL_ID` e `IEDUCAR_YEAR`.
- Moodle: `MOODLE_CATEGORY_ID`, `MOODLE_TEACHER_ROLE_ID` e `MOODLE_STUDENT_ROLE_ID`.

Mantenha as URLs internas do exemplo: `http://ieducar` e `http://moodle:8080`.
A preparação das APIs e dos tokens ainda é manual: veja
[Configuração das APIs](docs/CONFIGURACAO_APIS.md).
Os arquivos `.env` não devem ser versionados.

## Primeira instalação

**Execute somente em uma instalação nova do i-Educar:**

```bash
docker compose build api ieducar-fpm
docker compose up -d ieducar-db ieducar-redis
docker compose run --rm ieducar-php composer new-install
docker compose run --rm ieducar-php php artisan db:seed
docker compose up -d
```

Não repita `new-install` no ambiente já preparado: ele gera uma nova chave da aplicação.
O Moodle é instalado automaticamente quando seus volumes estão vazios.

## Iniciar e parar

Para o ambiente já preparado:

```bash
docker compose up -d --build
docker compose ps
```

- i-Educar: http://localhost
- Moodle: http://localhost:8080
- API e documentação: http://localhost:8000/docs
- Healthcheck: http://localhost:8000/health

Após alterar o `.env`, execute `docker compose up -d api`.

```bash
docker compose logs -f api
docker compose stop
```

Os dados ficam em volumes Docker. Não use `docker compose down -v` se quiser preservá-los.
Nesta máquina, o `.env` reutiliza volumes existentes com `COMPOSE_EXTERNAL_VOLUMES=true`;
em uma instalação nova, mantenha `false`, como no exemplo.
Não inicie outros containers de banco usando esses mesmos volumes simultaneamente.

## Sincronizar

Use [rest-client.http](rest-client.http) na extensão REST Client do VS Code.
Ela lê `SYNC_API_TOKEN` do `.env`.

1. Execute `POST /sync/teachers` para criar professores, cursos por turma/disciplina e vínculos docentes.
2. Execute `POST /sync/students` para criar alunos com matrícula ativa e matriculá-los nas disciplinas de suas turmas.

Ambos exigem `Authorization: Bearer SEU_SYNC_API_TOKEN`.
Comece com `{"dry_run": true}` para simular; use `{"dry_run": false}` para gravar.
Confira os erros nos resumos de contas, cursos e vínculos.
Reexecutar reconhece os registros existentes; não remove matrículas antigas nem atualiza contas.

As funcionalidades estão em [FUNCIONALIDADE_ALUNOS_MOODLE.md](FUNCIONALIDADE_ALUNOS_MOODLE.md).
Para dados de demonstração, consulte a [seed manual de professores](seeds/ieducar/README.md).
