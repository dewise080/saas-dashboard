"""
Direct database access to Evolution API for live status and data.
Uses Django's configured 'evolution' database connection.
"""
from django.db import connections
from contextlib import contextmanager


@contextmanager
def get_evolution_cursor():
    """Get a cursor for the evolution database."""
    cursor = connections['evolution'].cursor()
    try:
        yield cursor
    finally:
        cursor.close()


def get_instance_status(instance_name: str) -> dict | None:
    """
    Get live connection status for a WhatsApp instance directly from Evolution DB.
    
    Returns dict with:
    - connectionStatus: 'open', 'close', 'connecting'
    - ownerJid: connected WhatsApp number (e.g., '1234567890@s.whatsapp.net')
    - profileName: WhatsApp profile name
    - profilePicUrl: Profile picture URL
    """
    with get_evolution_cursor() as cursor:
        cursor.execute('''
            SELECT 
                "connectionStatus",
                "ownerJid",
                "profileName",
                "profilePicUrl",
                "updatedAt",
                "number"
            FROM "Instance"
            WHERE "name" = %s
            LIMIT 1
        ''', [instance_name])
        
        row = cursor.fetchone()
        if row:
            return {
                'connectionStatus': row[0],
                'ownerJid': row[1],
                'profileName': row[2],
                'profilePicUrl': row[3],
                'updatedAt': row[4],
                'number': row[5],
            }
        return None


def get_all_instances_status(instance_names: list) -> dict:
    """
    Get live status for multiple instances at once.
    Returns dict mapping instance_name -> status_dict
    """
    if not instance_names:
        return {}
    
    placeholders = ', '.join(['%s'] * len(instance_names))
    
    with get_evolution_cursor() as cursor:
        cursor.execute(f'''
            SELECT 
                "name",
                "connectionStatus",
                "ownerJid",
                "profileName",
                "profilePicUrl",
                "updatedAt",
                "number"
            FROM "Instance"
            WHERE "name" IN ({placeholders})
        ''', instance_names)
        
        results = {}
        for row in cursor.fetchall():
            results[row[0]] = {
                'connectionStatus': row[1],
                'ownerJid': row[2],
                'profileName': row[3],
                'profilePicUrl': row[4],
                'updatedAt': row[5],
                'number': row[6],
            }
        return results


def get_instance_contacts_count(instance_name: str) -> int:
    """Get total synced contacts count for an instance."""
    with get_evolution_cursor() as cursor:
        cursor.execute('''
            SELECT COUNT(*) FROM "Contact"
            WHERE "instanceId" = (
                SELECT "id" FROM "Instance" WHERE "name" = %s LIMIT 1
            )
        ''', [instance_name])
        row = cursor.fetchone()
        return row[0] if row else 0


def get_instance_messages_count(instance_name: str) -> int:
    """Get total messages count for an instance."""
    with get_evolution_cursor() as cursor:
        cursor.execute('''
            SELECT COUNT(*) FROM "Message"
            WHERE "instanceId" = (
                SELECT "id" FROM "Instance" WHERE "name" = %s LIMIT 1
            )
        ''', [instance_name])
        row = cursor.fetchone()
        return row[0] if row else 0


def get_instance_details(instance_name: str) -> dict | None:
    """Get full instance details from Evolution DB."""
    with get_evolution_cursor() as cursor:
        cursor.execute('''
            SELECT 
                "id",
                "name",
                "connectionStatus",
                "ownerJid",
                "profileName",
                "profilePicUrl",
                "number",
                "integration",
                "token",
                "createdAt",
                "updatedAt",
                "disconnectionAt",
                "disconnectionReasonCode"
            FROM "Instance"
            WHERE "name" = %s
            LIMIT 1
        ''', [instance_name])
        
        row = cursor.fetchone()
        if row:
            return {
                'id': row[0],
                'name': row[1],
                'connectionStatus': row[2],
                'ownerJid': row[3],
                'profileName': row[4],
                'profilePicUrl': row[5],
                'number': row[6],
                'integration': row[7],
                'token': row[8],
                'createdAt': row[9],
                'updatedAt': row[10],
                'disconnectionAt': row[11],
                'disconnectionReasonCode': row[12],
            }
        return None


def get_instance_chats(instance_name: str, limit: int = 50) -> list:
    """Get recent chats for an instance."""
    with get_evolution_cursor() as cursor:
        cursor.execute('''
            SELECT 
                c."id",
                c."remoteJid",
                c."name",
                c."unreadMessages",
                c."updatedAt"
            FROM "Chat" c
            JOIN "Instance" i ON c."instanceId" = i."id"
            WHERE i."name" = %s
            ORDER BY c."updatedAt" DESC
            LIMIT %s
        ''', [instance_name, limit])
        
        return [
            {
                'id': row[0],
                'remoteJid': row[1],
                'name': row[2],
                'unreadMessages': row[3],
                'updatedAt': row[4],
            }
            for row in cursor.fetchall()
        ]


def get_instance_contacts(instance_name: str, limit: int = 100) -> list:
    """Get contacts for an instance."""
    with get_evolution_cursor() as cursor:
        cursor.execute('''
            SELECT 
                c."id",
                c."remoteJid",
                c."pushName",
                c."profilePicUrl",
                c."updatedAt"
            FROM "Contact" c
            JOIN "Instance" i ON c."instanceId" = i."id"
            WHERE i."name" = %s
            ORDER BY c."updatedAt" DESC
            LIMIT %s
        ''', [instance_name, limit])
        
        return [
            {
                'id': row[0],
                'remoteJid': row[1],
                'pushName': row[2],
                'profilePicUrl': row[3],
                'updatedAt': row[4],
            }
            for row in cursor.fetchall()
        ]


def get_all_instances() -> list:
    """Get all instances from Evolution API."""
    with get_evolution_cursor() as cursor:
        cursor.execute('''
            SELECT 
                "id",
                "name",
                "connectionStatus",
                "ownerJid",
                "profileName",
                "profilePicUrl",
                "number",
                "createdAt",
                "updatedAt"
            FROM "Instance"
            ORDER BY "createdAt" DESC
        ''')
        
        return [
            {
                'id': row[0],
                'name': row[1],
                'connectionStatus': row[2],
                'ownerJid': row[3],
                'profileName': row[4],
                'profilePicUrl': row[5],
                'number': row[6],
                'createdAt': row[7],
                'updatedAt': row[8],
            }
            for row in cursor.fetchall()
        ]


def get_instance_settings(instance_name: str) -> dict | None:
    """Get settings for an instance."""
    with get_evolution_cursor() as cursor:
        cursor.execute('''
            SELECT 
                s."id",
                s."rejectCall",
                s."msgCall",
                s."groupsIgnore",
                s."alwaysOnline",
                s."readMessages",
                s."readStatus",
                s."syncFullHistory",
                s."createdAt",
                s."updatedAt"
            FROM "Setting" s
            JOIN "Instance" i ON s."instanceId" = i."id"
            WHERE i."name" = %s
            LIMIT 1
        ''', [instance_name])
        
        row = cursor.fetchone()
        if row:
            return {
                'id': row[0],
                'rejectCall': row[1],
                'msgCall': row[2],
                'groupsIgnore': row[3],
                'alwaysOnline': row[4],
                'readMessages': row[5],
                'readStatus': row[6],
                'syncFullHistory': row[7],
                'createdAt': row[8],
                'updatedAt': row[9],
            }
        return None


def get_instance_webhook(instance_name: str) -> dict | None:
    """Get webhook config for an instance."""
    with get_evolution_cursor() as cursor:
        cursor.execute('''
            SELECT 
                w."id",
                w."url",
                w."enabled",
                w."events",
                w."webhookByEvents",
                w."webhookBase64",
                w."createdAt",
                w."updatedAt"
            FROM "Webhook" w
            JOIN "Instance" i ON w."instanceId" = i."id"
            WHERE i."name" = %s
            LIMIT 1
        ''', [instance_name])
        
        row = cursor.fetchone()
        if row:
            return {
                'id': row[0],
                'url': row[1],
                'enabled': row[2],
                'events': row[3],
                'webhookByEvents': row[4],
                'webhookBase64': row[5],
                'createdAt': row[6],
                'updatedAt': row[7],
            }
        return None


def get_instance_recent_messages(instance_name: str, limit: int = 20) -> list:
    """Get recent messages for an instance."""
    with get_evolution_cursor() as cursor:
        cursor.execute('''
            SELECT 
                m."id",
                m."key",
                m."pushName",
                m."participant",
                m."messageType",
                m."message",
                m."messageTimestamp",
                m."status"
            FROM "Message" m
            JOIN "Instance" i ON m."instanceId" = i."id"
            WHERE i."name" = %s
            ORDER BY m."messageTimestamp" DESC
            LIMIT %s
        ''', [instance_name, limit])
        
        return [
            {
                'id': row[0],
                'key': row[1],
                'pushName': row[2],
                'participant': row[3],
                'messageType': row[4],
                'message': row[5],
                'messageTimestamp': row[6],
                'status': row[7],
            }
            for row in cursor.fetchall()
        ]


def get_instance_labels(instance_name: str) -> list:
    """Get labels for an instance."""
    with get_evolution_cursor() as cursor:
        cursor.execute('''
            SELECT 
                l."id",
                l."labelId",
                l."name",
                l."color",
                l."createdAt"
            FROM "Label" l
            JOIN "Instance" i ON l."instanceId" = i."id"
            WHERE i."name" = %s
            ORDER BY l."name"
        ''', [instance_name])
        
        return [
            {
                'id': row[0],
                'labelId': row[1],
                'name': row[2],
                'color': row[3],
                'createdAt': row[4],
            }
            for row in cursor.fetchall()
        ]


def get_instance_stats(instance_name: str) -> dict:
    """Get comprehensive stats for an instance."""
    with get_evolution_cursor() as cursor:
        # Get instance ID first
        cursor.execute('SELECT "id" FROM "Instance" WHERE "name" = %s LIMIT 1', [instance_name])
        row = cursor.fetchone()
        if not row:
            return {}
        
        instance_id = row[0]
        
        # Get counts
        cursor.execute('SELECT COUNT(*) FROM "Contact" WHERE "instanceId" = %s', [instance_id])
        contacts_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM "Message" WHERE "instanceId" = %s', [instance_id])
        messages_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM "Chat" WHERE "instanceId" = %s', [instance_id])
        chats_count = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM "Label" WHERE "instanceId" = %s', [instance_id])
        labels_count = cursor.fetchone()[0]
        
        # Get unread messages count
        cursor.execute('SELECT COALESCE(SUM("unreadMessages"), 0) FROM "Chat" WHERE "instanceId" = %s', [instance_id])
        unread_count = cursor.fetchone()[0]
        
        return {
            'contacts': contacts_count,
            'messages': messages_count,
            'chats': chats_count,
            'labels': labels_count,
            'unread': unread_count,
        }
