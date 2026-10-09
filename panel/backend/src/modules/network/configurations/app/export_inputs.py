from src.modules.accounts.customers.app.policies import CustomerAccessPolicy
from src.modules.network.configurations.domain.results import (
    ConfigurationServerFacts,
    ConnectionEndpoint,
    ProfileFacts,
    ServerConfigurationInput,
    ServerProfileInput,
)


class ServerExportInputs:
    @staticmethod
    def profile(facts: ProfileFacts) -> ServerProfileInput:
        return ServerProfileInput(
            profile_id=facts.profile.id,
            generation=facts.subscription.renewal_count,
            request_state=facts.request_state,
            configuration_id=facts.profile.configuration_id,
            services_available=CustomerAccessPolicy.services_available(
                facts.customer
            ),
            status=facts.subscription.status,
            expires_at=facts.subscription.expires_at,
            quota_bytes=facts.subscription.quota_bytes,
            used_bytes=facts.subscription.used_bytes,
            encrypted_credentials=facts.profile.encrypted_credentials,
            client_address=facts.profile.client_address,
        )

    @staticmethod
    def configuration(
        facts: ConfigurationServerFacts,
    ) -> ServerConfigurationInput:
        return ServerConfigurationInput(
            endpoint=ConnectionEndpoint(
                facts.configuration.id,
                facts.node.public_host,
                facts.configuration.listen_port,
            ),
            revision=facts.configuration.revision,
            core_kind=facts.core.kind,
            protocol=facts.configuration.protocol,
            encrypted_settings=facts.configuration.encrypted_settings,
        )
