from django.db import migrations


# Allowlists explícitas e congeladas nesta migration; sem serialização da linha inteira.
SQL = """
CREATE FUNCTION auditoria_registrar_evento(
    p_tipo_evento text, p_operacao text, p_tabela_origem text,
    p_registro_id text, p_empresa_id bigint, p_loja_id bigint,
    p_dados_anteriores jsonb, p_dados_novos jsonb
)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO auditoria_eventoauditoria (
        tipo_evento, operacao, tabela_origem, registro_id, empresa_id, loja_id,
        origem, usuario_id, credencial_id, ocorrido_em, dados_anteriores, dados_novos
    ) VALUES (
        p_tipo_evento, p_operacao, p_tabela_origem, p_registro_id, p_empresa_id, p_loja_id,
        NULLIF(current_setting('retorna.auditoria_origem', true), ''),
        NULLIF(current_setting('retorna.auditoria_usuario_id', true), '')::bigint,
        NULLIF(current_setting('retorna.auditoria_credencial_id', true), '')::bigint,
        clock_timestamp(), p_dados_anteriores, p_dados_novos
    );
END;
$$;

CREATE FUNCTION auditoria_compra_fatos()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    anteriores jsonb;
    novos jsonb;
    tipo text;
    registro text;
    loja bigint;
    empresa bigint;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        anteriores := jsonb_build_object(
            'id', OLD.id,
            'resgate_id', OLD.resgate_id,
            'loja_id', OLD.loja_id,
            'cliente_id', OLD.cliente_id,
            'credencial_origem_id', OLD.credencial_origem_id,
            'identificador_externo', OLD.identificador_externo,
            'valor', OLD.valor,
            'ocorrida_em', OLD.ocorrida_em,
            'criada_em', OLD.criada_em
        );
    END IF;
    IF TG_OP <> 'DELETE' THEN
        novos := jsonb_build_object(
            'id', NEW.id,
            'resgate_id', NEW.resgate_id,
            'loja_id', NEW.loja_id,
            'cliente_id', NEW.cliente_id,
            'credencial_origem_id', NEW.credencial_origem_id,
            'identificador_externo', NEW.identificador_externo,
            'valor', NEW.valor,
            'ocorrida_em', NEW.ocorrida_em,
            'criada_em', NEW.criada_em
        );
    END IF;
    IF TG_OP = 'UPDATE' AND anteriores = novos THEN
        RETURN NULL;
    END IF;

    IF TG_OP = 'INSERT' THEN
        registro := NEW.id::text;
        loja := NEW.loja_id;
    ELSE
        -- UPDATE de PK/Loja não desloca a evidência para o novo registro/tenant.
        registro := OLD.id::text;
        loja := OLD.loja_id;
    END IF;
    SELECT l.empresa_id INTO empresa FROM empresas_loja l WHERE l.id = loja;
    tipo := CASE TG_OP
        WHEN 'INSERT' THEN 'COMPRA_CRIADA'
        WHEN 'UPDATE' THEN 'COMPRA_ALTERADA'
        WHEN 'DELETE' THEN 'COMPRA_EXCLUIDA'
    END;
    PERFORM auditoria_registrar_evento(
        tipo, TG_OP, TG_TABLE_NAME, registro, empresa, loja, anteriores, novos
    );
    RETURN NULL;
END;
$$;

CREATE TRIGGER auditoria_compra_fatos_trg
AFTER INSERT OR UPDATE OR DELETE ON fidelidade_compra
FOR EACH ROW EXECUTE FUNCTION auditoria_compra_fatos();

CREATE FUNCTION auditoria_resgate_fatos()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    anteriores jsonb;
    novos jsonb;
    tipo text;
    registro text;
    loja bigint;
    empresa bigint;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        anteriores := jsonb_build_object(
            'id', OLD.id,
            'loja_id', OLD.loja_id,
            'cliente_id', OLD.cliente_id,
            'credencial_origem_id', OLD.credencial_origem_id,
            'identificador_externo', OLD.identificador_externo,
            'pontos_resgatados', OLD.pontos_resgatados,
            'resgate_minimo_pontos_aplicado', OLD.resgate_minimo_pontos_aplicado,
            'incremento_resgate_pontos_aplicado', OLD.incremento_resgate_pontos_aplicado,
            'valor_monetario_por_ponto_aplicado', OLD.valor_monetario_por_ponto_aplicado,
            'valor_desconto', OLD.valor_desconto,
            'resgatado_em', OLD.resgatado_em
        );
    END IF;
    IF TG_OP <> 'DELETE' THEN
        novos := jsonb_build_object(
            'id', NEW.id,
            'loja_id', NEW.loja_id,
            'cliente_id', NEW.cliente_id,
            'credencial_origem_id', NEW.credencial_origem_id,
            'identificador_externo', NEW.identificador_externo,
            'pontos_resgatados', NEW.pontos_resgatados,
            'resgate_minimo_pontos_aplicado', NEW.resgate_minimo_pontos_aplicado,
            'incremento_resgate_pontos_aplicado', NEW.incremento_resgate_pontos_aplicado,
            'valor_monetario_por_ponto_aplicado', NEW.valor_monetario_por_ponto_aplicado,
            'valor_desconto', NEW.valor_desconto,
            'resgatado_em', NEW.resgatado_em
        );
    END IF;
    IF TG_OP = 'UPDATE' AND anteriores = novos THEN
        RETURN NULL;
    END IF;

    IF TG_OP = 'INSERT' THEN
        registro := NEW.id::text;
        loja := NEW.loja_id;
    ELSE
        -- UPDATE de PK/Loja não desloca a evidência para o novo registro/tenant.
        registro := OLD.id::text;
        loja := OLD.loja_id;
    END IF;
    SELECT l.empresa_id INTO empresa FROM empresas_loja l WHERE l.id = loja;
    tipo := CASE TG_OP
        WHEN 'INSERT' THEN 'RESGATE_CRIADO'
        WHEN 'UPDATE' THEN 'RESGATE_ALTERADO'
        WHEN 'DELETE' THEN 'RESGATE_EXCLUIDO'
    END;
    PERFORM auditoria_registrar_evento(
        tipo, TG_OP, TG_TABLE_NAME, registro, empresa, loja, anteriores, novos
    );
    RETURN NULL;
END;
$$;

CREATE TRIGGER auditoria_resgate_fatos_trg
AFTER INSERT OR UPDATE OR DELETE ON fidelidade_resgate
FOR EACH ROW EXECUTE FUNCTION auditoria_resgate_fatos();

CREATE FUNCTION auditoria_estorno_resgate_fatos()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    anteriores jsonb;
    novos jsonb;
    tipo text;
    registro text;
    loja bigint;
    empresa bigint;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        anteriores := jsonb_build_object(
            'id', OLD.id,
            'resgate_id', OLD.resgate_id,
            'loja_id', OLD.loja_id,
            'cliente_id', OLD.cliente_id,
            'credencial_origem_id', OLD.credencial_origem_id,
            'identificador_externo', OLD.identificador_externo,
            'devolve_pontos_aplicado', OLD.devolve_pontos_aplicado,
            'estornado_em', OLD.estornado_em
        );
    END IF;
    IF TG_OP <> 'DELETE' THEN
        novos := jsonb_build_object(
            'id', NEW.id,
            'resgate_id', NEW.resgate_id,
            'loja_id', NEW.loja_id,
            'cliente_id', NEW.cliente_id,
            'credencial_origem_id', NEW.credencial_origem_id,
            'identificador_externo', NEW.identificador_externo,
            'devolve_pontos_aplicado', NEW.devolve_pontos_aplicado,
            'estornado_em', NEW.estornado_em
        );
    END IF;
    IF TG_OP = 'UPDATE' AND anteriores = novos THEN
        RETURN NULL;
    END IF;

    IF TG_OP = 'INSERT' THEN
        registro := NEW.id::text;
        loja := NEW.loja_id;
    ELSE
        -- UPDATE de PK/Loja não desloca a evidência para o novo registro/tenant.
        registro := OLD.id::text;
        loja := OLD.loja_id;
    END IF;
    SELECT l.empresa_id INTO empresa FROM empresas_loja l WHERE l.id = loja;
    tipo := CASE TG_OP
        WHEN 'INSERT' THEN 'ESTORNO_RESGATE_CRIADO'
        WHEN 'UPDATE' THEN 'ESTORNO_RESGATE_ALTERADO'
        WHEN 'DELETE' THEN 'ESTORNO_RESGATE_EXCLUIDO'
    END;
    PERFORM auditoria_registrar_evento(
        tipo, TG_OP, TG_TABLE_NAME, registro, empresa, loja, anteriores, novos
    );
    RETURN NULL;
END;
$$;

CREATE TRIGGER auditoria_estorno_resgate_fatos_trg
AFTER INSERT OR UPDATE OR DELETE ON fidelidade_estornoresgate
FOR EACH ROW EXECUTE FUNCTION auditoria_estorno_resgate_fatos();

CREATE FUNCTION auditoria_lote_pontos_fatos()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    anteriores jsonb;
    novos jsonb;
    tipo text;
    registro text;
    loja bigint;
    empresa bigint;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        anteriores := jsonb_build_object(
            'id', OLD.id,
            'compra_id', OLD.compra_id,
            'cliente_id', OLD.cliente_id,
            'pontos_base', OLD.pontos_base,
            'pontos_concedidos', OLD.pontos_concedidos,
            'pontos_por_real_aplicado', OLD.pontos_por_real_aplicado,
            'multiplicador_pontos_aplicado', OLD.multiplicador_pontos_aplicado,
            'precisao_pontos_aplicada', OLD.precisao_pontos_aplicada,
            'modo_arredondamento_aplicado', OLD.modo_arredondamento_aplicado,
            'validade_pontos_meses_aplicada', OLD.validade_pontos_meses_aplicada,
            'adquiridos_em', OLD.adquiridos_em,
            'expira_em', OLD.expira_em,
            'criado_em', OLD.criado_em,
            'beneficios_aplicados', OLD.beneficios_aplicados
        );
    END IF;
    IF TG_OP <> 'DELETE' THEN
        novos := jsonb_build_object(
            'id', NEW.id,
            'compra_id', NEW.compra_id,
            'cliente_id', NEW.cliente_id,
            'pontos_base', NEW.pontos_base,
            'pontos_concedidos', NEW.pontos_concedidos,
            'pontos_por_real_aplicado', NEW.pontos_por_real_aplicado,
            'multiplicador_pontos_aplicado', NEW.multiplicador_pontos_aplicado,
            'precisao_pontos_aplicada', NEW.precisao_pontos_aplicada,
            'modo_arredondamento_aplicado', NEW.modo_arredondamento_aplicado,
            'validade_pontos_meses_aplicada', NEW.validade_pontos_meses_aplicada,
            'adquiridos_em', NEW.adquiridos_em,
            'expira_em', NEW.expira_em,
            'criado_em', NEW.criado_em,
            'beneficios_aplicados', NEW.beneficios_aplicados
        );
    END IF;
    IF TG_OP = 'UPDATE' AND anteriores = novos THEN
        RETURN NULL;
    END IF;

    -- Lote não audita INSERT; a Compra OLD define o tenant da evidência.
    registro := OLD.id::text;
    SELECT c.loja_id, l.empresa_id INTO loja, empresa
    FROM fidelidade_compra c
    JOIN empresas_loja l ON l.id = c.loja_id
    WHERE c.id = OLD.compra_id;
    tipo := CASE TG_OP
        WHEN 'UPDATE' THEN 'LOTE_PONTOS_ALTERADO'
        WHEN 'DELETE' THEN 'LOTE_PONTOS_EXCLUIDO'
    END;
    PERFORM auditoria_registrar_evento(
        tipo, TG_OP, TG_TABLE_NAME, registro, empresa, loja, anteriores, novos
    );
    RETURN NULL;
END;
$$;

CREATE TRIGGER auditoria_lote_pontos_fatos_trg
AFTER UPDATE OR DELETE ON fidelidade_lotepontos
FOR EACH ROW EXECUTE FUNCTION auditoria_lote_pontos_fatos();
"""

REVERSE_SQL = """
DROP TRIGGER auditoria_compra_fatos_trg ON fidelidade_compra;
DROP TRIGGER auditoria_resgate_fatos_trg ON fidelidade_resgate;
DROP TRIGGER auditoria_estorno_resgate_fatos_trg ON fidelidade_estornoresgate;
DROP TRIGGER auditoria_lote_pontos_fatos_trg ON fidelidade_lotepontos;
DROP FUNCTION auditoria_compra_fatos();
DROP FUNCTION auditoria_resgate_fatos();
DROP FUNCTION auditoria_estorno_resgate_fatos();
DROP FUNCTION auditoria_lote_pontos_fatos();
DROP FUNCTION auditoria_registrar_evento(text, text, text, text, bigint, bigint, jsonb, jsonb);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("auditoria", "0001_initial"),
        ("fidelidade", "0008_compra_resgate"),
    ]

    operations = [migrations.RunSQL(SQL, reverse_sql=REVERSE_SQL)]
