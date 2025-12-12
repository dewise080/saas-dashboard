from rest_framework import serializers

class EmailTemplateStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["draft", "ready", "approved", "rejected"])
    status_message = serializers.CharField(required=False, allow_blank=True)
