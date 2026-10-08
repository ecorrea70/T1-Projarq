# Seed manual do i-Educar

Utilitário isolado para **ambiente local de demonstração**, fora do núcleo do
monolito. Escreve diretamente no PostgreSQL do i-Educar somente para preparar
dados fictícios. A sincronização continua exclusivamente pelas APIs; esta seed
não é importada pela aplicação, nem executada pelo Docker Compose.

Cria um professor fictício por turma ativa já existente no escopo, com pessoa
física (sem CPF), servidor ativo, função com `professor=1`, alocação na escola,
vínculo docente na turma e seus componentes curriculares já cadastrados para o
ano. Não cria alunos, escolas, turmas ou componentes. Não apaga dados, não
substitui docentes existentes e não cria contas no Moodle.

O nome é `Professor Demo Turma {código}` e o e-mail marcador é
`seed-professor-turma-{código}@example.org`. Esses e-mails são fictícios: não
servem para receber mensagens ou recuperar senhas. A função se chama
`Professor (seed monolito)`, abreviatura `DEMO-T1`.

## Executar

Requer Docker e o serviço `ieducar-db` do Compose do monolito em execução. Defaults:
banco/usuário `ieducar`, instituição `1`, escolas
`2,3`, ano `2026`. Confirme que o container é o banco local, nunca produção.

```bash
# Simula os INSERTs e desfaz a transação (padrão).
bash seeds/ieducar/run.sh --dry-run

# Persiste os dados.
bash seeds/ieducar/run.sh --apply

# Reexecutar não deve criar duplicatas.
bash seeds/ieducar/run.sh --apply
```

É possível mudar o escopo explicitamente:

```bash
SEED_INSTITUTION_ID=1 SEED_SCHOOL_IDS=2,3 SEED_YEAR=2026 \
  bash seeds/ieducar/run.sh --dry-run
```

`SEED_DB_NAME` e `SEED_DB_USER` permitem ajustar o banco. `SEED_CONTAINER`
é opcional e permite usar um container externo em vez do serviço do Compose.
Não lê nem altera os arquivos `.env` dos projetos. O SQL corresponde ao schema
da versão local de i-Educar, incluindo `turma_serie` e os vínculos de disciplinas.

A operação é transacional e reexecutável: usa os marcadores exclusivos da seed
e um lock para serializar suas execuções. Falhas ou marcadores incompatíveis
cancelam a transação inteira, sem corrigir/inativar cadastros existentes.
O dry-run também valida constraints reais, mas PostgreSQL não desfaz avanços
de sequences: podem aparecer lacunas nos IDs, sem dados persistidos.

Depois de aplicar, use `POST /sync/teachers` com `{"dry_run": true}` para
confirmar que os dados são encontrados **pela API**. Criar usuários no Moodle
é uma operação separada (`{"dry_run": false}`). Os vínculos desta seed são
no i-Educar; o endpoint de professores cria os cursos e vínculos no Moodle.
