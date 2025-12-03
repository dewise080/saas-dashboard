from django.db import models


class SafeJSONField(models.JSONField):
    """JSONField that tolerates already-parsed values coming from the driver."""

    def from_db_value(self, value, expression, connection):
        if isinstance(value, (dict, list)):
            return value
        return super().from_db_value(value, expression, connection)


class N8nBase(models.Model):
    class Meta:
        abstract = True
        managed = False
        app_label = "n8n_mirror"


class WorkflowEntity(N8nBase):
    id = models.CharField(primary_key=True, max_length=36)
    name = models.CharField(max_length=128)
    active = models.BooleanField()
    nodes = SafeJSONField()
    connections = SafeJSONField()
    createdAt = models.DateTimeField()
    updatedAt = models.DateTimeField()
    settings = SafeJSONField(null=True, blank=True)
    staticData = SafeJSONField(null=True, blank=True)
    pinData = SafeJSONField(null=True, blank=True)
    versionId = models.CharField(max_length=36)
    triggerCount = models.IntegerField()
    meta = SafeJSONField(null=True, blank=True)
    parentFolderId = models.CharField(max_length=36, null=True, blank=True)
    isArchived = models.BooleanField()
    versionCounter = models.IntegerField()
    description = models.TextField(null=True, blank=True)

    class Meta(N8nBase.Meta):
        db_table = "workflow_entity"


class ExecutionEntity(N8nBase):
    id = models.BigIntegerField(primary_key=True)
    finished = models.BooleanField()
    mode = models.CharField(max_length=255)
    retryOf = models.CharField(max_length=255, null=True, blank=True)
    retrySuccessId = models.CharField(max_length=255, null=True, blank=True)
    startedAt = models.DateTimeField(null=True, blank=True)
    stoppedAt = models.DateTimeField(null=True, blank=True)
    waitTill = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=255)
    workflowId = models.CharField(max_length=36)
    deletedAt = models.DateTimeField(null=True, blank=True)
    createdAt = models.DateTimeField()

    class Meta(N8nBase.Meta):
        db_table = "execution_entity"


class ExecutionData(N8nBase):
    executionId = models.OneToOneField(
        ExecutionEntity, on_delete=models.DO_NOTHING, db_column="executionId", primary_key=True
    )
    workflowData = models.TextField()
    data = models.TextField()

    class Meta(N8nBase.Meta):
        db_table = "execution_data"


class ExecutionAnnotations(N8nBase):
    executionId = models.OneToOneField(
        ExecutionEntity, on_delete=models.DO_NOTHING, db_column="executionId", primary_key=True
    )
    vote = models.CharField(max_length=6, null=True, blank=True)
    note = models.TextField(null=True, blank=True)
    createdAt = models.DateTimeField()
    updatedAt = models.DateTimeField()

    class Meta(N8nBase.Meta):
        db_table = "execution_annotations"


class ExecutionMetadata(N8nBase):
    executionId = models.ForeignKey(ExecutionEntity, on_delete=models.DO_NOTHING, db_column="executionId")
    key = models.CharField(max_length=255)
    value = models.TextField()

    class Meta(N8nBase.Meta):
        db_table = "execution_metadata"
        unique_together = (("executionId", "key"),)


class CredentialsEntity(N8nBase):
    id = models.CharField(primary_key=True, max_length=36)
    name = models.CharField(max_length=128)
    data = models.TextField()
    type = models.CharField(max_length=128)
    createdAt = models.DateTimeField()
    updatedAt = models.DateTimeField()
    isManaged = models.BooleanField()

    class Meta(N8nBase.Meta):
        db_table = "credentials_entity"


class SharedCredentials(N8nBase):
    """Junction table linking credentials to projects (and thus to users)."""
    credentialsId = models.CharField(primary_key=True, max_length=36)
    projectId = models.CharField(max_length=36)
    role = models.TextField()
    createdAt = models.DateTimeField()
    updatedAt = models.DateTimeField()

    class Meta(N8nBase.Meta):
        db_table = "shared_credentials"
        unique_together = (("credentialsId", "projectId"),)


class Project(N8nBase):
    """n8n project - users are linked to projects."""
    id = models.CharField(primary_key=True, max_length=36)
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=36)
    createdAt = models.DateTimeField()
    updatedAt = models.DateTimeField()

    class Meta(N8nBase.Meta):
        db_table = "project"


class ProjectRelation(N8nBase):
    """Links users to projects."""
    projectId = models.CharField(max_length=36)
    userId = models.CharField(max_length=36)
    role = models.TextField()
    createdAt = models.DateTimeField()
    updatedAt = models.DateTimeField()

    class Meta(N8nBase.Meta):
        db_table = "project_relation"
        unique_together = (("projectId", "userId"),)


class UserEntity(N8nBase):
    id = models.UUIDField(primary_key=True)
    email = models.CharField(max_length=255, null=True, blank=True)
    firstName = models.CharField(max_length=32, null=True, blank=True)
    lastName = models.CharField(max_length=32, null=True, blank=True)
    password = models.CharField(max_length=255, null=True, blank=True)
    personalizationAnswers = SafeJSONField(null=True, blank=True)
    createdAt = models.DateTimeField()
    updatedAt = models.DateTimeField()
    settings = SafeJSONField(null=True, blank=True)
    disabled = models.BooleanField()
    mfaEnabled = models.BooleanField()
    mfaSecret = models.TextField(null=True, blank=True)
    mfaRecoveryCodes = models.TextField(null=True, blank=True)
    lastActiveAt = models.DateField(null=True, blank=True)
    roleSlug = models.CharField(max_length=128)

    class Meta(N8nBase.Meta):
        db_table = "user"


class UserApiKeys(N8nBase):
    id = models.CharField(primary_key=True, max_length=36)
    userId = models.ForeignKey(UserEntity, on_delete=models.DO_NOTHING, db_column="userId")
    label = models.CharField(max_length=100)
    apiKey = models.CharField(max_length=255, unique=True, db_column="apiKey")
    createdAt = models.DateTimeField()
    updatedAt = models.DateTimeField()
    scopes = models.TextField(null=True, blank=True)
    audience = models.CharField(max_length=255)

    class Meta(N8nBase.Meta):
        db_table = "user_api_keys"
        unique_together = (("userId", "label"),)


class TagEntity(N8nBase):
    id = models.CharField(primary_key=True, max_length=36)
    name = models.CharField(max_length=24)
    createdAt = models.DateTimeField()
    updatedAt = models.DateTimeField()

    class Meta(N8nBase.Meta):
        db_table = "tag_entity"


class SharedWorkflow(N8nBase):
    workflowId = models.CharField(primary_key=True, max_length=36)
    projectId = models.CharField(max_length=36)
    role = models.TextField()
    createdAt = models.DateTimeField()
    updatedAt = models.DateTimeField()

    class Meta(N8nBase.Meta):
        db_table = "shared_workflow"
        unique_together = (("workflowId", "projectId"),)


class WebhookEntity(N8nBase):
    webhookPath = models.CharField(primary_key=True, max_length=255)
    method = models.CharField(max_length=255)
    node = models.CharField(max_length=255)
    webhookId = models.CharField(max_length=255, null=True, blank=True)
    pathLength = models.IntegerField(null=True, blank=True)
    workflowId = models.CharField(max_length=36)

    class Meta(N8nBase.Meta):
        db_table = "webhook_entity"
        unique_together = (("webhookPath", "method"),)
