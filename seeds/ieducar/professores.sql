-- Executado somente pelo utilitário manual run.sh, em uma transação.
-- O marcador de e-mail identifica exclusivamente os dados desta demonstração.
SELECT pg_advisory_xact_lock(741026, 1);

DO $$
DECLARE
    institution integer := current_setting('seed.institution')::integer;
    schools integer[] := string_to_array(current_setting('seed.schools'), ',')::integer[];
    school_year integer := current_setting('seed.year')::integer;
    creator integer;
    role_id integer;
    person_id integer;
    employment_id integer;
    assignment_id integer;
    fixture_email text;
    fixture_count integer;
    class_row record;
    class_count integer := 0;
    people_created integer := 0;
    assignments_created integer := 0;
    components_created integer := 0;
    inserted integer;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pmieducar.instituicao WHERE cod_instituicao = institution AND ativo = 1) THEN
        RAISE EXCEPTION 'Instituição inexistente ou inativa: %', institution;
    END IF;
    IF EXISTS (
        SELECT 1 FROM unnest(schools) s(id)
        WHERE NOT EXISTS (SELECT 1 FROM pmieducar.escola e
            WHERE e.cod_escola = s.id AND e.ref_cod_instituicao = institution AND e.ativo = 1)
    ) THEN
        RAISE EXCEPTION 'Há escola inexistente, inativa ou de outra instituição no escopo';
    END IF;
    SELECT min(cod_usuario) INTO creator FROM pmieducar.usuario WHERE ativo = 1;
    IF creator IS NULL THEN RAISE EXCEPTION 'Não há usuário ativo para registrar os cadastros'; END IF;
    IF NOT EXISTS (SELECT 1 FROM pmieducar.turma
        WHERE ativo = 1 AND ref_cod_instituicao = institution
          AND ref_ref_cod_escola = ANY(schools) AND ano = school_year) THEN
        RAISE EXCEPTION 'Não há turmas ativas nesse escopo';
    END IF;

    SELECT count(*), min(cod_funcao) INTO fixture_count, role_id
    FROM pmieducar.funcao WHERE ref_cod_instituicao = institution
        AND nm_funcao = 'Professor (seed monolito)' AND abreviatura = 'DEMO-T1';
    IF fixture_count > 1 THEN RAISE EXCEPTION 'Função da seed duplicada; nenhuma alteração aplicada'; END IF;
    IF role_id IS NULL THEN
        INSERT INTO pmieducar.funcao
            (ref_usuario_cad, nm_funcao, abreviatura, professor, data_cadastro, ativo, ref_cod_instituicao)
        VALUES (creator, 'Professor (seed monolito)', 'DEMO-T1', 1, now(), 1, institution)
        RETURNING cod_funcao INTO role_id;
    ELSIF NOT EXISTS (SELECT 1 FROM pmieducar.funcao WHERE cod_funcao = role_id AND professor = 1 AND ativo = 1) THEN
        RAISE EXCEPTION 'Função da seed foi alterada/inativada; nenhuma alteração aplicada';
    END IF;

    FOR class_row IN
        SELECT cod_turma, ref_ref_cod_escola AS school_id, ref_ref_cod_serie AS series_id, turma_turno_id
        FROM pmieducar.turma WHERE ativo = 1 AND ref_cod_instituicao = institution
          AND ref_ref_cod_escola = ANY(schools) AND ano = school_year ORDER BY cod_turma
    LOOP
        class_count := class_count + 1;
        IF NOT EXISTS (
            SELECT 1 FROM modules.componente_curricular_ano_escolar ca
            WHERE ca.ano_escolar_id IN (
                SELECT COALESCE(ts.serie_id, class_row.series_id)
                FROM (SELECT 1) dummy LEFT JOIN pmieducar.turma_serie ts ON ts.turma_id = class_row.cod_turma
            ) AND school_year = ANY(ca.anos_letivos)
        ) THEN
            RAISE EXCEPTION 'Turma % não possui componentes curriculares para o ano; transação cancelada', class_row.cod_turma;
        END IF;
        fixture_email := format('seed-professor-turma-%s@example.org', class_row.cod_turma);
        SELECT count(*), min(idpes) INTO fixture_count, person_id FROM cadastro.pessoa WHERE email = fixture_email;
        IF fixture_count > 1 THEN RAISE EXCEPTION 'E-mail da seed duplicado: %', fixture_email; END IF;
        IF person_id IS NULL THEN
            INSERT INTO cadastro.pessoa (nome, email, data_cad, tipo, situacao, origem_gravacao, operacao)
            VALUES (format('Professor Demo Turma %s', class_row.cod_turma), fixture_email, now(), 'F', 'A', 'M', 'I')
            RETURNING idpes INTO person_id;
            INSERT INTO cadastro.fisica (idpes, data_nasc, sexo, nacionalidade, origem_gravacao, data_cad, operacao)
            VALUES (person_id, DATE '1985-01-01', 'M', 1, 'M', now(), 'I');
            people_created := people_created + 1;
        ELSIF NOT EXISTS (SELECT 1 FROM cadastro.pessoa p JOIN cadastro.fisica f USING(idpes)
            WHERE p.idpes = person_id AND p.nome = format('Professor Demo Turma %s', class_row.cod_turma)
              AND p.tipo = 'F' AND p.situacao = 'A') THEN
            RAISE EXCEPTION 'Marcador da seed ocupado por cadastro incompatível: %', fixture_email;
        END IF;

        IF NOT EXISTS (SELECT 1 FROM pmieducar.servidor WHERE cod_servidor = person_id AND ref_cod_instituicao = institution) THEN
            INSERT INTO pmieducar.servidor (cod_servidor, ref_cod_instituicao, carga_horaria, data_cadastro, ativo)
            VALUES (person_id, institution, 40, now(), 1);
        ELSIF NOT EXISTS (SELECT 1 FROM pmieducar.servidor WHERE cod_servidor = person_id
            AND ref_cod_instituicao = institution AND ativo = 1) THEN
            RAISE EXCEPTION 'Servidor da seed inativado: %', person_id;
        END IF;
        SELECT count(*), min(cod_servidor_funcao) INTO fixture_count, employment_id
        FROM pmieducar.servidor_funcao WHERE ref_cod_servidor = person_id
            AND ref_ref_cod_instituicao = institution AND ref_cod_funcao = role_id;
        IF fixture_count > 1 THEN RAISE EXCEPTION 'Função duplicada para servidor %', person_id; END IF;
        IF employment_id IS NULL THEN
            INSERT INTO pmieducar.servidor_funcao (ref_cod_servidor, ref_ref_cod_instituicao, ref_cod_funcao, matricula)
            VALUES (person_id, institution, role_id, format('DEMO-T1-%s', class_row.cod_turma))
            RETURNING cod_servidor_funcao INTO employment_id;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pmieducar.servidor_alocacao WHERE ref_cod_servidor = person_id
            AND ref_ref_cod_instituicao = institution AND ref_cod_escola = class_row.school_id
            AND ano = school_year AND ativo = 1 AND ref_cod_servidor_funcao = employment_id) THEN
            INSERT INTO pmieducar.servidor_alocacao (ref_cod_servidor, ref_ref_cod_instituicao,
                ref_cod_escola, ref_usuario_cad, data_cadastro, ativo, periodo, carga_horaria,
                ref_cod_servidor_funcao, ano, data_admissao)
            VALUES (person_id, institution, class_row.school_id, creator, now(), 1,
                COALESCE(class_row.turma_turno_id, 1), interval '40 hours', employment_id,
                school_year, make_date(school_year, 1, 1));
        END IF;
        SELECT count(*), min(id) INTO fixture_count, assignment_id FROM modules.professor_turma
        WHERE servidor_id = person_id AND instituicao_id = institution
            AND turma_id = class_row.cod_turma AND ano = school_year;
        IF fixture_count > 1 THEN RAISE EXCEPTION 'Vínculo docente duplicado para turma %', class_row.cod_turma; END IF;
        IF assignment_id IS NULL THEN
            INSERT INTO modules.professor_turma (ano, instituicao_id, servidor_id, turma_id,
                funcao_exercida, tipo_vinculo, permite_lancar_faltas_componente, updated_at, turno_id, data_inicial)
            VALUES (school_year, institution, person_id, class_row.cod_turma, 1, 2, 1, now(),
                class_row.turma_turno_id, make_date(school_year, 1, 1))
            RETURNING id INTO assignment_id;
            assignments_created := assignments_created + 1;
        END IF;
        INSERT INTO modules.professor_turma_disciplina (professor_turma_id, componente_curricular_id)
        SELECT DISTINCT assignment_id, ca.componente_curricular_id
        FROM modules.componente_curricular_ano_escolar ca
        WHERE ca.ano_escolar_id IN (
            SELECT COALESCE(ts.serie_id, class_row.series_id)
            FROM (SELECT 1) dummy LEFT JOIN pmieducar.turma_serie ts ON ts.turma_id = class_row.cod_turma
        ) AND school_year = ANY(ca.anos_letivos)
        ON CONFLICT (professor_turma_id, componente_curricular_id) DO NOTHING;
        GET DIAGNOSTICS inserted = ROW_COUNT;
        components_created := components_created + inserted;
    END LOOP;
    RAISE NOTICE 'Turmas: %, pessoas criadas: %, vínculos docentes criados: %, vínculos de componentes criados: %',
        class_count, people_created, assignments_created, components_created;
END $$;
