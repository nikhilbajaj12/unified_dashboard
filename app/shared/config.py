from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Temporal — unauthenticated HTTP API via internal FQDN
    temporal_base_url: str = Field(default="")
    temporal_namespaces: str = Field(default="default")

    phoenix_host: str = Field(default="http://localhost:6006")
    phoenix_api_key: str = Field(default="")


    azure_subscription_id: str = Field(default="")
    azure_tenant_id: str = Field(default="")
    azure_client_id: str = Field(default="")
    azure_client_secret: str = Field(default="")
    azure_resource_group: str = Field(default="")
    azure_openai_resource: str = Field(default="")

    app_port: int = Field(default=8000)

    model_config = {"env_file": ".env"}


settings = Settings()
