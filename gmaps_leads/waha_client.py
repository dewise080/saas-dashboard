import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class WahaClientError(Exception):
    """Raised when the WAHA client is misconfigured or fails permanently."""


class WahaClient:
    """Small helper for talking to WAHA (WhatsApp HTTP API)."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        session: Optional[str] = None,
        timeout: Optional[int] = None,
        contacts_path: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self.base_url = (base_url or getattr(settings, "WAHA_SERVICE_URL", "") or "").rstrip("/")
        self.api_key = api_key or getattr(settings, "WAHA_API_KEY", None)
        self.session = session or getattr(settings, "WAHA_SESSION", None) or "default"
        self.timeout = timeout or getattr(settings, "WAHA_TIMEOUT", 15)
        self.contacts_path = contacts_path or getattr(settings, "WAHA_CONTACTS_PATH", None)
        user = username or getattr(settings, "WAHA_USERNAME", None) or getattr(settings, "WAHA_SWAGGER_USERNAME", None)
        pwd = password or getattr(settings, "WAHA_PASSWORD", None) or getattr(settings, "WAHA_SWAGGER_PASSWORD", None)
        self.auth = (user, pwd) if user and pwd else None

        if not self.base_url:
            raise WahaClientError("WAHA base URL is not configured (SERVICE_URL_WAHA missing).")

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    @property
    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            # WAHA expects X-Api-Key; keep a duplicate header for compatibility
            headers["X-Api-Key"] = self.api_key
            headers["X-API-Key"] = self.api_key
        return headers

    def _safe_json(self, response: requests.Response) -> Any:
        try:
            return response.json()
        except Exception:
            return response.text

    def _contact_paths(self) -> List[str]:
        """
        Order of endpoints to try when pushing contacts.
        """
        default_path = f"/api/{self.session}/contacts"
        fallbacks = ["/api/contacts", "/contacts"]
        paths: List[str] = []
        if self.contacts_path:
            paths.append(self.contacts_path)
        paths.append(default_path)
        paths.extend(fallbacks)
        seen = set()
        deduped = []
        for path in paths:
            cleaned = path if path.startswith("/") else f"/{path}"
            if cleaned not in seen:
                deduped.append(cleaned)
                seen.add(cleaned)
        return deduped

    def _contact_paths_for(self, chat_id: str) -> List[str]:
        """
        Build ordered contact endpoints for a specific chat_id.
        """
        paths: List[str] = []
        if self.contacts_path:
            if "{chatId}" in self.contacts_path:
                paths.append(self.contacts_path.format(chatId=chat_id))
            else:
                paths.append(f"{self.contacts_path.rstrip('/')}/{chat_id}")

        paths.append(f"/api/{self.session}/contacts/{chat_id}")
        paths.append(f"/api/contacts/{chat_id}")
        paths.append(f"/contacts/{chat_id}")

        seen = set()
        deduped = []
        for path in paths:
            cleaned = path if path.startswith("/") else f"/{path}"
            if cleaned not in seen:
                deduped.append(cleaned)
                seen.add(cleaned)
        return deduped

    def _absolute_url(self, path: str) -> str:
        return urljoin(f"{self.base_url}/", path.lstrip("/"))

    # ------------------------------------------------------------------ #
    # Public actions
    # ------------------------------------------------------------------ #
    def health(self) -> Dict[str, Any]:
        """
        Try a handful of lightweight status endpoints.
        """
        candidate_paths = [
            f"/api/{self.session}/status",
            "/api/status",
            "/health",
            "/healthz",
        ]
        attempts = []
        for path in candidate_paths:
            url = self._absolute_url(path)
            try:
                resp = requests.get(url, headers=self._headers, timeout=self.timeout, auth=self.auth)
                payload = self._safe_json(resp)
                attempts.append({"url": url, "status": resp.status_code})
                if resp.ok:
                    return {
                        "ok": True,
                        "status_code": resp.status_code,
                        "url": url,
                        "payload": payload,
                        "attempts": attempts,
                    }
            except requests.RequestException as exc:
                attempts.append({"url": url, "error": str(exc)})

        return {"ok": False, "attempts": attempts}

    def sync_contacts(self, contacts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Push a batch of contacts to WAHA.
        """
        summary = {
            "success": True,
            "synced": 0,
            "failures": [],
            "attempts": {},
        }

        for contact in contacts:
            chat_id = contact.get("chatId") or contact.get("chat_id")
            if not chat_id:
                summary["failures"].append({"contact": contact, "error": "Missing chatId"})
                summary["success"] = False
                continue

            payload = {
                "firstName": contact.get("name") or contact.get("business_name") or "",
                "lastName": contact.get("category") or "",
                "phone": contact.get("phone"),
            }

            attempts: List[Dict[str, Any]] = []
            for path in self._contact_paths_for(chat_id):
                url = self._absolute_url(path)
                try:
                    resp = requests.put(
                        url,
                        json=payload,
                        headers=self._headers,
                        timeout=self.timeout,
                        auth=self.auth,
                    )
                    body = self._safe_json(resp)
                    attempts.append({"url": url, "status": resp.status_code})
                    if resp.ok:
                        summary["synced"] += 1
                        break
                    attempts[-1]["payload"] = body
                except requests.RequestException as exc:
                    attempts.append({"url": url, "error": str(exc)})
            else:
                summary["success"] = False
                summary["failures"].append({"chatId": chat_id, "attempts": attempts, "payload": payload})

            summary["attempts"][chat_id] = attempts

        return summary

    def send_text(
        self,
        chat_id: str,
        text: str,
        quoted_message_id: Optional[str] = None,
        reply_to: Optional[str] = None,
        phone: Optional[str] = None,
        session: Optional[str] = None,
        link_preview: Optional[bool] = None,
        link_preview_high_quality: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Send a plain text message. Tries a few common WAHA endpoints.
        """
        payload: Dict[str, Any] = {
            "chatId": chat_id,
            "text": text,
            "session": session or self.session,
        }
        if phone:
            payload["phone"] = phone if phone.startswith("+") else f"+{phone}"
        if quoted_message_id:
            payload["quotedMessageId"] = quoted_message_id
        if reply_to:
            payload["reply_to"] = reply_to
        if link_preview is not None:
            payload["linkPreview"] = link_preview
        if link_preview_high_quality is not None:
            payload["linkPreviewHighQuality"] = link_preview_high_quality

        candidate_paths = [
            f"/api/{self.session}/sendText",
            "/api/sendText",
            "/sendText",
            f"/api/{self.session}/messages/text",
            "/api/messages/text",
        ]

        attempts: List[Dict[str, Any]] = []
        for path in candidate_paths:
            url = self._absolute_url(path)
            try:
                resp = requests.post(
                    url,
                    json=payload,
                    headers=self._headers,
                    timeout=self.timeout,
                    auth=self.auth,
                )
                body = self._safe_json(resp)
                attempts.append({"url": url, "status": resp.status_code})
                if resp.ok:
                    return {
                        "success": True,
                        "status_code": resp.status_code,
                        "url": url,
                        "payload": payload,
                        "response": body,
                        "attempts": attempts,
                    }
                attempts[-1]["payload"] = body
            except requests.RequestException as exc:
                attempts.append({"url": url, "error": str(exc)})

        return {"success": False, "payload": payload, "attempts": attempts}
