"""Firebase Admin SDK の初期化。

Admin SDK は Firestore セキュリティルールをバイパスするため、
「クライアントは read のみ / 書き込みは全部ここを通す」という
設計（firebase/firestore.rules 参照）が成立する。
"""

from functools import lru_cache

import firebase_admin
import google.auth.credentials
from firebase_admin import credentials
from firebase_admin import firestore as admin_firestore
from google.cloud.firestore import Client as FirestoreClient

from app.config import get_settings


class _EmulatorCredentials(credentials.Base):  # type: ignore[misc]  # SDK に型情報がない
    """エミュレータ接続用のダミー資格情報。

    firebase_admin は資格情報を必須とするが、エミュレータは認証を行わない。
    ADC を要求されてローカル開発が止まらないよう匿名資格情報を返す。
    """

    def get_credential(self) -> google.auth.credentials.Credentials:
        return google.auth.credentials.AnonymousCredentials()  # type: ignore[no-untyped-call]


@lru_cache
def get_app() -> firebase_admin.App:
    settings = get_settings()

    if firebase_admin._apps:
        return firebase_admin.get_app()

    # FIRESTORE_EMULATOR_HOST が設定されていれば google-cloud-firestore が
    # 自動的にエミュレータへ向く。ここでは資格情報だけを差し替える。
    cred = _EmulatorCredentials() if settings.use_emulator else credentials.ApplicationDefault()

    return firebase_admin.initialize_app(cred, {"projectId": settings.firebase_project_id})


@lru_cache
def get_db() -> FirestoreClient:
    client: FirestoreClient = admin_firestore.client(get_app())
    return client
