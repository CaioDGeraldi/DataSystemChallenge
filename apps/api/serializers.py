from rest_framework import serializers


class HealthSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["ok"])


class CredencialSerializer(serializers.Serializer):
    identificador = serializers.CharField()
    nome = serializers.CharField()


class EmpresaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nome = serializers.CharField()


class LojaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nome = serializers.CharField()
    cidade = serializers.CharField()


class ContextoSerializer(serializers.Serializer):
    credencial = CredencialSerializer()
    empresa = EmpresaSerializer()
    escopo = serializers.ChoiceField(choices=["EMPRESA", "LOJAS"])
    lojas = LojaSerializer(many=True)


class ErroSerializer(serializers.Serializer):
    codigo = serializers.CharField()
    mensagem = serializers.CharField()
    detalhes = serializers.JSONField(required=False)


class EnvelopeErroSerializer(serializers.Serializer):
    erro = ErroSerializer()
