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

    # **作問（Gemini）をモックにするかどうか。これだけが判断材料。**
    # 記事は切り替えの対象外で、いつも Wikipedia から取る。
    #
    # キーの有無から推測すると「キーは検証用に置いてあるが実際は呼びたくない」
    # といった意図が表現できず、逆に「本番のつもりがキー未設定で黙ってモック」
    # という事故も起こる。切り替えたい意図は、変数として明示的に書く。
    #
    # 既定は True。うっかり実 API を叩いて課金される事故のほうが痛いので、
    # 実際に作問させるときだけ明示的に false にする。
    use_mock: bool = True

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"

    # Wikimedia は連絡先を含む User-Agent がないと 403 を返す。
    # 例: "PreQuiz/1.0 (https://example.com; contact@example.com)"
    wikimedia_user_agent: str = ""

    cors_origins: str = "http://localhost:5173"

    # 記事プールの構築など、運用者だけが叩く操作の合言葉。
    # 未設定なら、その操作は誰にも通さない（開けっ放しにしない）。
    # プール構築は Wikipedia と Gemini を何十回も呼ぶので、
    # 無防備なまま置くと URL を知っているだけで課金させられる。
    admin_token: str = ""

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
    def missing_settings(self) -> list[str]:
        """いまの構成で足りていない設定。

        記事はモックでも実データなので、`WIKIMEDIA_USER_AGENT` は常に要る。
        `GEMINI_API_KEY` が要るのは、実際に作問させるときだけ。
        """
        missing = []
        if not self.wikimedia_user_agent.strip():
            missing.append("WIKIMEDIA_USER_AGENT")
        if not self.use_mock and not self.gemini_api_key.strip():
            missing.append("GEMINI_API_KEY")
        return missing


@lru_cache
def get_settings() -> Settings:
    return Settings()
