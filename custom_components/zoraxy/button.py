"""Button platform for the Zoraxy integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import ZoraxyError
from .const import DOMAIN
from .coordinator import ZoraxyConfigEntry
from .entity import ZoraxyCertEntity

# ACME renewal blocks until Zoraxy finishes the challenge; serialize presses
# instead of letting several run against the same instance at once.
PARALLEL_UPDATES = 1

RENEW_CERT_DESCRIPTION = ButtonEntityDescription(
    key="renew_cert",
    translation_key="renew_cert",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZoraxyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Zoraxy buttons."""
    coordinator = entry.runtime_data

    known_certs: set[str] = set()

    @callback
    def _async_add_cert_buttons() -> None:
        """Add renew buttons for newly discovered certificates."""
        new_entities = [
            ZoraxyRenewCertButton(
                coordinator,
                RENEW_CERT_DESCRIPTION,
                filename,
                on_remove=known_certs.discard,
            )
            for filename in coordinator.data.certs
            if filename not in known_certs
        ]
        if new_entities:
            known_certs.update(entity.cert_filename for entity in new_entities)
            async_add_entities(new_entities)

    _async_add_cert_buttons()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_cert_buttons))


class ZoraxyRenewCertButton(ZoraxyCertEntity, ButtonEntity):
    """Request a new certificate for a domain via ACME."""

    async def async_press(self) -> None:
        """Trigger the certificate renewal."""
        cert = self.cert
        if cert is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="cert_no_longer_exists",
                translation_placeholders={"filename": self.cert_filename},
            )
        try:
            await self.coordinator.client.async_renew_certificate(cert)
        except ZoraxyError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="cert_renewal_failed",
                translation_placeholders={"domain": cert.domain, "error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()
