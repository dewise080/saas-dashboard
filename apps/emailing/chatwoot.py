import logging
from typing import Any, Dict, Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class ChatwootClient:
    def __init__(self) -> None:
        self.enabled = getattr(settings, "CHATWOOT_ENABLED", False)
        self.base_url = (getattr(settings, "CHATWOOT_BASE_URL", "") or "").rstrip("/")
        self.account_id = getattr(settings, "CHATWOOT_ACCOUNT_ID", None)
        self.inbox_id = getattr(settings, "CHATWOOT_INBOX_ID", None)
        self.api_token = getattr(settings, "CHATWOOT_API_TOKEN", None)
        env_api_path = getattr(settings, "CHATWOOT_API_PATH", None)
        default_path = "/api/v1"
        if env_api_path is not None:
            # Avoid double /api when base_url already endswith /api and default path is used
            if (env_api_path in ("", "/api/v1")) and self.base_url.endswith("/api"):
                self.api_path = "/v1"
            elif (env_api_path in ("", "/api/v1")) and self.base_url.endswith("/api/v1"):
                self.api_path = ""
            else:
                self.api_path = (env_api_path or "").strip()
        elif self.base_url.endswith("/api"):
            # Base already points at /api, so only append /v1 by default
            self.api_path = "/v1"
        elif self.base_url.endswith("/api/v1"):
            self.api_path = ""
        else:
            self.api_path = default_path
        self.api_path = self.api_path.rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.base_url and self.account_id and self.inbox_id and self.api_token)

    def _headers(self) -> Dict[str, str]:
        return {"Content-Type": "application/json", "api_access_token": self.api_token}

    def _url(self, path: str) -> str:
        prefix = self.api_path
        if prefix:
            prefix = "/" + prefix.lstrip("/")
        return f"{self.base_url}{prefix}{path}"

    def _request(self, method: str, path: str, retry_platform: bool = True, **kwargs) -> Dict[str, Any]:
        url = self._url(path)
        resp = requests.request(method, url, headers=self._headers(), timeout=10, **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    # ------------------------------------------------------------------ #
    # Contact helpers
    # ------------------------------------------------------------------ #
    def _flatten_payload(self, payload: Any) -> Any:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            return payload.get("payload") or payload.get("data") or payload
        return payload

    def find_contact(self, query: str) -> Optional[Dict[str, Any]]:
        try:
            res = self._request("GET", f"/accounts/{self.account_id}/contacts/search", params={"q": query})
            data = self._flatten_payload(res)
            if isinstance(data, list) and data:
                return data[0]
            if isinstance(data, dict) and data.get("id"):
                return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("Chatwoot search failed for %s: %s", query, exc)
        return None

    def ensure_contact_any(
        self,
        *,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        name: Optional[str] = None,
        custom_attributes: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Find or create a contact using phone/email. Falls back to creation.
        """
        lookup = phone or email
        contact = self.find_contact(lookup) if lookup else None
        if contact:
            return contact

        payload = {
            "name": name or (email or phone) or "Unknown",
            "phone_number": phone,
            "email": email,
            "custom_attributes": custom_attributes or {},
        }
        try:
            created = self._request("POST", f"/accounts/{self.account_id}/contacts", json=payload)
            if isinstance(created, dict) and created.get("id"):
                return created
            # Fallback: search again if no id returned
            contact = self.find_contact(lookup) if lookup else None
            if contact:
                return contact
            return created
        except Exception as exc:  # noqa: BLE001
            logger.warning("Chatwoot create contact failed (%s): %s", lookup, exc)
            # Attempt to re-fetch in case of duplicate
            contact = self.find_contact(lookup) if lookup else None
            if contact:
                return contact
            raise

    def ensure_contact_inbox(self, contact_id: int, inbox_id: Optional[int], source_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Attach a contact to an inbox with a source_id (e.g., phone/jid).
        """
        if not inbox_id:
            return {}
        payload = {"inbox_id": int(inbox_id)}
        if source_id:
            payload["source_id"] = source_id
        return self._request(
            "POST",
            f"/accounts/{self.account_id}/contacts/{contact_id}/contact_inboxes",
            json=payload,
        )

    def ensure_contact(self, email: str, name: Optional[str] = None, custom_attributes: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Find or create a Chatwoot contact by email."""
        try:
            search = self._request("GET", f"/accounts/{self.account_id}/contacts/search", params={"q": email})
            payload = {}
            if isinstance(search, list):
                payload = {"data": search}
            elif isinstance(search, dict):
                payload = search.get("payload") or search
            if isinstance(payload, list):
                data = payload
            elif isinstance(payload, dict):
                data = payload.get("data") or payload
            else:
                data = payload
            if isinstance(data, list) and data:
                return data[0]
            if isinstance(data, dict) and data.get("id"):
                return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("Chatwoot search contact failed: %s", exc)

        data = {
            "email": email,
            "name": name or email,
            "custom_attributes": custom_attributes or {},
        }
        try:
            return self._request("POST", f"/accounts/{self.account_id}/contacts", json=data)
        except Exception as exc:  # noqa: BLE001
            # If contact exists, return the existing one
            if "already been taken" in str(exc) or "422" in str(exc):
                try:
                    search = self._request("GET", f"/accounts/{self.account_id}/contacts/search", params={"q": email}, retry_platform=False)
                    payload = {}
                    if isinstance(search, list):
                        payload = {"data": search}
                    elif isinstance(search, dict):
                        payload = search.get("payload") or search
                    if isinstance(payload, list):
                        data = payload
                    elif isinstance(payload, dict):
                        data = payload.get("data") or payload
                    else:
                        data = payload
                    if isinstance(data, list) and data:
                        return data[0]
                    if isinstance(data, dict) and data.get("id"):
                        return data
                except Exception as inner:  # noqa: BLE001
                    logger.warning("Chatwoot search after 422 failed: %s", inner)
            raise

    def ensure_conversation(self, contact_id: int, subject: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        data = {
            "inbox_id": int(self.inbox_id),
            "contact_id": contact_id,
            "additional_attributes": metadata or {},
        }
        conv = self._request("POST", f"/accounts/{self.account_id}/conversations", json=data)
        # Set custom attributes for subject if returned structure permits
        if subject:
            try:
                self._request(
                    "PATCH",
                    f"/accounts/{self.account_id}/conversations/{conv.get('id')}",
                    json={"custom_attributes": {"subject": subject}},
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("Chatwoot set subject failed: %s", exc)
        return conv

    def append_message(
        self,
        conversation_id: int,
        content: str,
        subject: str,
        html_body: str,
        from_email: str,
        to_email: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = {
            "message_type": "outgoing",
            "content": content or "(no text body)",
            "content_attributes": {
                "email": {
                    "subject": subject,
                    "from": from_email,
                    "to": [to_email],
                    "message": html_body,
                },
                "metadata": metadata or {},
            },
        }
        return self._request(
            "POST",
            f"/accounts/{self.account_id}/conversations/{conversation_id}/messages",
            json=payload,
        )

    def log_outgoing_email(
        self,
        *,
        to_email: str,
        subject: str,
        text_body: str,
        html_body: str,
        from_email: str,
        context: Dict[str, Any],
        send_metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not self.configured:
            return {}

        contact = self.ensure_contact(
            email=to_email,
            name=context.get("recipient_name") if context else None,
            custom_attributes={"company": context.get("company")} if context else {},
        )
        conv = self.ensure_conversation(
            contact_id=contact.get("id"),
            subject=subject,
            metadata={"campaign": send_metadata.get("campaign_id"), "campaign_recipient": send_metadata.get("campaign_recipient_id")},
        )
        msg = self.append_message(
            conversation_id=conv.get("id"),
            content=text_body,
            subject=subject,
            html_body=html_body,
            from_email=from_email,
            to_email=to_email,
            metadata=send_metadata,
        )
        return {
            "contact_id": contact.get("id"),
            "conversation_id": conv.get("id"),
            "message_id": msg.get("id"),
        }
