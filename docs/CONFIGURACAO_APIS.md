# Configuração das APIs

Esta preparação é manual e precisa ser feita uma vez, após iniciar as plataformas.
O Compose não cria serviços, permissões ou tokens automaticamente.

## i-Educar

Para gerar o token REST de alunos com matrícula, execute:

```bash
docker compose exec ieducar-fpm php artisan admin:token integracao-monolito
```

Copie o token retornado para `IEDUCAR_TOKEN` no `.env` do monolito.
Não gere outro token se já houver uma credencial válida.

Para a API legada de professores e catálogo de turmas/disciplinas, acesse
`/configuracoes/configuracoes-de-sistema`. Na categoria
**Integração entre iEducar e iDiário**, configure ou consulte
**Chave de acesso ao i-Educar** e copie seu valor para `IEDUCAR_ACCESS_KEY`.
Essa chave é diferente do token REST. Nesta versão, a configuração salva pela
interface sobrescreve `API_ACCESS_KEY`; alterar apenas o arquivo não basta.

Configure `IEDUCAR_INSTITUTION_ID`, `IEDUCAR_SCHOOL_ID` e `IEDUCAR_YEAR`.
O campo de escolas aceita códigos separados por vírgula, como `2,3`.
A sincronização usa somente as APIs, sem fallback para consultas ao banco.

## Moodle

Na administração do Moodle:

1. Habilite os web services e o protocolo REST.
2. Crie e habilite um serviço de integração.
3. Autorize um usuário com as permissões necessárias e gere seu token.
4. Copie o token para `MOODLE_TOKEN` no `.env` do monolito.

Adicione ao serviço estas funções:

- `core_user_get_users_by_field`
- `core_user_create_users`
- `core_webservice_get_site_info`
- `core_course_get_categories`
- `core_course_get_courses_by_field`
- `core_course_create_courses`
- `core_enrol_get_enrolled_users`
- `enrol_manual_enrol_users`

O usuário do serviço precisa das permissões `moodle/user:viewdetails`,
`moodle/user:create`, `moodle/user:update`, `moodle/course:create`,
`moodle/course:viewparticipants`, `enrol/manual:enrol` e `moodle/role:assign`,
nos contextos correspondentes. Deve poder atribuir os papéis Professor e Estudante.
Confira também as permissões exigidas na documentação de API da própria instalação.

Habilite a matrícula manual globalmente e como método padrão dos novos cursos.
Nos cursos existentes, habilite esse método individualmente se necessário.

Configure os IDs no `.env`:

- `MOODLE_CATEGORY_ID`: categoria existente em Cursos → Gerenciar cursos e categorias.
- `MOODLE_TEACHER_ROLE_ID`: papel Professor.
- `MOODLE_STUDENT_ROLE_ID`: papel Estudante.

Os IDs aparecem na URL ao abrir a categoria ou o papel em
Usuários → Permissões → Definir papéis. Confirme-os na instalação; não presuma valores fixos.
O papel é atribuído dentro do curso, não globalmente à conta.

## Aplicar as credenciais

Defina também `SYNC_API_TOKEN`, um segredo próprio para proteger os endpoints do monolito.
Depois de alterar o `.env`, recarregue a configuração:

```bash
docker compose up -d api
```

Simule a sincronização antes de gravar. A simulação consulta os sistemas,
mas não comprova todas as permissões de escrita.

Se precisar enviar recuperação de senha ou mensagens de boas-vindas,
configure SMTP no Moodle. As contas recebem senhas aleatórias que não são exibidas.
