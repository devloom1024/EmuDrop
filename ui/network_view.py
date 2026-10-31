"""Network / proxy settings view.

Rendered as a simple list of rows (label + current value) that is navigated
with the D-pad. Text values are edited with the existing on-screen keyboard.
"""
from typing import List, Sequence, Tuple

import sdl2

from utils.config import Config
from utils.logger import logger
from utils.theme import Theme
from .base_view import BaseView


class NetworkView(BaseView):
    """Settings list for the HTTP proxy configuration."""

    def render(self, selected: int, rows: Sequence[Tuple[str, str]], status: str = "") -> None:
        try:
            self.render_title("Network")

            row_width = min(int(760 * Config.SCALE_FACTOR), Config.SCREEN_WIDTH - int(80 * Config.SCALE_FACTOR))
            row_height = int(46 * Config.SCALE_FACTOR)
            row_gap = int(8 * Config.SCALE_FACTOR)
            start_x = (Config.SCREEN_WIDTH - row_width) // 2
            start_y = int(105 * Config.SCALE_FACTOR)

            for index, (label, value) in enumerate(rows):
                y = start_y + index * (row_height + row_gap)
                is_selected = index == selected

                rect = sdl2.SDL_Rect(int(start_x), int(y), int(row_width), row_height)
                bg_color = Theme.CARD_SELECTED if is_selected else Theme.CARD_BG
                sdl2.SDL_SetRenderDrawColor(self.renderer, *bg_color, 255)
                sdl2.SDL_RenderFillRect(self.renderer, rect)

                if is_selected:
                    sdl2.SDL_SetRenderDrawColor(self.renderer, *Theme.TEXT_ACCENT, 255)
                else:
                    sdl2.SDL_SetRenderDrawColor(self.renderer, *Theme.CARD_BORDER, 255)
                sdl2.SDL_RenderDrawRect(self.renderer, rect)

                text_y = int(y + (row_height - int(24 * Config.SCALE_FACTOR)) // 2)
                padding = int(18 * Config.SCALE_FACTOR)

                self.render_text(
                    label,
                    int(start_x + padding),
                    text_y,
                    color=Theme.TEXT_PRIMARY if is_selected else Theme.TEXT_SECONDARY,
                    center=False,
                )

                # Right aligned value
                value_texture, value_width, _ = self.create_text_texture(
                    value, Theme.TEXT_ACCENT if is_selected else Theme.TEXT_SECONDARY
                )
                if value_texture:
                    sdl2.SDL_DestroyTexture(value_texture)
                    self.render_text(
                        value,
                        int(start_x + row_width - padding - value_width),
                        text_y,
                        color=Theme.TEXT_ACCENT if is_selected else Theme.TEXT_SECONDARY,
                        center=False,
                    )

            # Status / help line
            help_text = "A: Edit / Select    B: Back    Up/Down: Move    Left/Right: Toggle"
            self.render_text(
                help_text,
                Config.SCREEN_WIDTH // 2,
                Config.SCREEN_HEIGHT - int(70 * Config.SCALE_FACTOR),
                color=Theme.TEXT_PLACEHOLDER,
                center=True,
            )

            if status:
                self.render_text(
                    status,
                    Config.SCREEN_WIDTH // 2,
                    Config.SCREEN_HEIGHT - int(105 * Config.SCALE_FACTOR),
                    color=Theme.TEXT_HIGHLIGHT,
                    center=True,
                )
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(f"Error rendering network view: {exc}", exc_info=True)
