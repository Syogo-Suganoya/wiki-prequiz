"""環境変数の読み込みと検証。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    firebase_project_id: str = "prequiz-local"

    # この2つが設定されているとき Admin SDK は本番ではなくエミュレータへ接続する。
    # 本番デプロイ時は未設定になっていることを起動時に確認する。
    firestore_emulator_host: str | None = None
    firebase_auth_emulator_host: str | None = None

    # モックで動かすかどうか。**これだけが判断材料**。
    # キーの有無から推測すると「キーは検証用に置いてあるが実際は呼びたくない」
    # といった意図が表現できず、逆に「本番のつもりがキー未設定で黙ってモック」
    # という事故も起こる。切り替えたい意図は、変数として明示的に書く。
    #
    # 既定は True。うっかり実 API を叩いて課金される事故のほうが痛いので、
    # 実データを使うときだけ明示的に false にする。
    use_mock: bool = True

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"

    # Wikimedia は連絡先を含む User-Agent がないと 403 を返す。
    # 例: "PreQuiz/1.0 (https://example.com; contact@example.com)"
    wikimedia_user_agent: str = ""

    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def use_emulator(self) -> bool:
        return self.firestore_emulator_host is not None

    @property
    def is_mock(self) -> bool:
        return self.use_mock

    @property
    def missing_for_real(self) -> list[str]:
        """実データで動かすのに足りていない設定。"""
        missing = []
        if not self.gemini_api_key.strip():
            missing.append("GEMINI_API_KEY")
        if not self.wikimedia_user_agent.strip():
            missing.append("WIKIMEDIA_USER_AGENT")
        return missing


@lru_cache
def get_settings() -> Settings:
    return Settings()
