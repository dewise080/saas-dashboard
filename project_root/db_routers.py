class N8nRouter:
    """Route all n8n_mirror models to the n8n DB in read-only mode."""

    route_app_labels = {"n8n_mirror"}

    def db_for_read(self, model, **hints):
        if model._meta.app_label in self.route_app_labels:
            return "n8n"
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label in self.route_app_labels:
            raise PermissionError("Write operations are blocked for n8n_mirror models.")
        return None

    def allow_relation(self, obj1, obj2, **hints):
        if obj1._meta.app_label in self.route_app_labels or obj2._meta.app_label in self.route_app_labels:
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in self.route_app_labels:
            return False
        return None
