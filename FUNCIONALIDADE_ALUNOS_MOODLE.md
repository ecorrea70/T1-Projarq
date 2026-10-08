# Funcionalidades implementadas

- Criação de usuários no Moodle para alunos com matrícula ativa no i-Educar.
- Criação de usuários no Moodle para professores com vínculo docente ativo no i-Educar.
- Criação de um curso no Moodle para cada disciplina de cada turma.
- Matrícula dos professores nos cursos correspondentes, com o papel de Professor.
- Matrícula dos alunos nas disciplinas de suas turmas ativas, com o papel de Estudante.
- Integração entre os sistemas pelas APIs.
- Prevenção de duplicatas de usuários, cursos e vínculos.
- Simulação da sincronização e apresentação dos resultados e erros.
- Autenticação dos endpoints e controle de execuções simultâneas.
- Execução do monolito, i-Educar, Moodle e dependências pelo mesmo Docker Compose.
- i-Educar integrado ao repositório como Git submodule, com versão fixada.
- Seed de professores fictícios para demonstração no i-Educar.
- Arquivo de requisições para o REST Client do VS Code.
