from __future__ import annotations

from scanner.libs.schemas import AlertPayload


class SlackWebhookFormatter:
    def format(self, alert: AlertPayload) -> dict:
        return {
            "text": f"[{alert.route}] {alert.title or alert.listing_pk}",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*{alert.title or alert.listing_pk}*\n"
                            f"EV: ${alert.ev:.2f} | EV lower: ${alert.ev_lower:.2f} | "
                            f"ActionScore: {alert.action_score:.1f}"
                        ),
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "\n".join(f"- {reason}" for reason in alert.why_it_matters),
                    },
                },
            ],
        }


class GenericWebhookFormatter:
    def format(self, alert: AlertPayload) -> dict:
        return alert.model_dump(mode="json")
