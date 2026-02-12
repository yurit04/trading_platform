"""
Risk manager for enforcing risk limits and monitoring.
"""
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import logging
import numpy as np

from ..core.event_bus import EventBus
from ..core.event import OrderEvent, RiskEvent
from ..core.enums import OrderSide, EventType
from ..portfolio.portfolio import Portfolio


logger = logging.getLogger(__name__)


class RiskManager:
    """
    Enforces risk limits and monitors portfolio risk.

    Validates orders pre-trade and monitors portfolio risk post-trade.
    All limits are config-driven with sensible defaults.
    """

    def __init__(
        self,
        event_bus: EventBus,
        portfolio: Portfolio,
        config: Optional[Dict[str, Any]] = None
    ):
        self.event_bus = event_bus
        self.portfolio = portfolio
        self.config = config or {}

        # Config-driven risk limits
        self.max_position_size = self.config.get('max_position_size', 0.10)
        self.max_order_value = self.config.get('max_order_value', 0.10)
        self.max_concentration = self.config.get('max_concentration', 0.25)
        self.max_leverage = self.config.get('max_leverage', 1.0)
        self.max_drawdown = self.config.get('max_drawdown', -0.20)
        self.stop_loss_pct = self.config.get('stop_loss_pct', 0.10)

        logger.info(
            f"RiskManager initialized: max_position={self.max_position_size:.0%}, "
            f"max_order={self.max_order_value:.0%}, max_concentration={self.max_concentration:.0%}, "
            f"max_leverage={self.max_leverage}, max_drawdown={self.max_drawdown:.0%}"
        )

    def validate_order(self, event: OrderEvent, current_price: float) -> Tuple[bool, str]:
        """
        Pre-trade risk gate called by ExecutionEngine before execution.

        Args:
            event: Order event to validate
            current_price: Current market price for the symbol

        Returns:
            (passed, reason) — True if order passes all checks
        """
        portfolio_value = self.portfolio.total_value
        if portfolio_value <= 0:
            return False, "Portfolio value is zero or negative"

        order_value = event.quantity * current_price
        is_buy = event.side in (OrderSide.BUY, OrderSide.BUY_TO_COVER)

        # 1. Max order value check (buys only — don't block de-risking sells)
        order_pct = order_value / portfolio_value
        if is_buy and order_pct > self.max_order_value:
            reason = (
                f"Order value {order_pct:.1%} of portfolio exceeds "
                f"max_order_value limit {self.max_order_value:.1%}"
            )
            self._publish_risk_event('POSITION_SIZE', 'WARNING', reason, {
                'symbol': event.symbol, 'order_pct': order_pct,
                'limit': self.max_order_value
            })
            return False, reason

        # 2. Resulting position weight check (for buys)
        if is_buy:
            current_position = self.portfolio.get_position(event.symbol)
            current_qty = current_position.quantity if current_position else 0
            new_qty = current_qty + event.quantity
            new_position_value = new_qty * current_price

            # Check max_position_size
            new_weight = new_position_value / portfolio_value
            if new_weight > self.max_position_size:
                reason = (
                    f"Resulting position weight {new_weight:.1%} for {event.symbol} "
                    f"exceeds max_position_size limit {self.max_position_size:.1%}"
                )
                self._publish_risk_event('POSITION_SIZE', 'WARNING', reason, {
                    'symbol': event.symbol, 'new_weight': new_weight,
                    'limit': self.max_position_size
                })
                return False, reason

            # Check max_concentration
            if new_weight > self.max_concentration:
                reason = (
                    f"Resulting position weight {new_weight:.1%} for {event.symbol} "
                    f"exceeds max_concentration limit {self.max_concentration:.1%}"
                )
                self._publish_risk_event('CONCENTRATION', 'WARNING', reason, {
                    'symbol': event.symbol, 'new_weight': new_weight,
                    'limit': self.max_concentration
                })
                return False, reason

            # 3. Cash check for buys
            estimated_cost = order_value
            if estimated_cost > self.portfolio.cash:
                reason = (
                    f"Insufficient cash: order costs ~${estimated_cost:,.2f} "
                    f"but only ${self.portfolio.cash:,.2f} available"
                )
                self._publish_risk_event('POSITION_SIZE', 'WARNING', reason, {
                    'symbol': event.symbol, 'order_cost': estimated_cost,
                    'available_cash': self.portfolio.cash
                })
                return False, reason

        # 4. Drawdown check — block new buys if max drawdown breached
        if is_buy:
            current_dd = self._current_drawdown()
            if current_dd < self.max_drawdown:
                reason = (
                    f"Portfolio drawdown {current_dd:.1%} exceeds "
                    f"max_drawdown limit {self.max_drawdown:.1%} — new buys blocked"
                )
                self._publish_risk_event('DRAWDOWN', 'CRITICAL', reason, {
                    'current_drawdown': current_dd,
                    'limit': self.max_drawdown
                })
                return False, reason

        return True, ""

    def check_portfolio_risk(self) -> List[dict]:
        """
        Post-trade portfolio risk monitoring. Returns list of alerts.

        Returns:
            List of alert dicts with {limit_type, severity, message, details}
        """
        alerts = []
        portfolio_value = self.portfolio.total_value
        if portfolio_value <= 0:
            return alerts

        # Drawdown check
        current_dd = self._current_drawdown()
        if current_dd < self.max_drawdown:
            alerts.append({
                'limit_type': 'DRAWDOWN',
                'severity': 'CRITICAL',
                'message': f'Portfolio drawdown {current_dd:.1%} exceeds limit {self.max_drawdown:.1%}',
                'details': {'current_drawdown': current_dd, 'limit': self.max_drawdown}
            })
        elif current_dd < self.max_drawdown * 0.8:
            alerts.append({
                'limit_type': 'DRAWDOWN',
                'severity': 'WARNING',
                'message': f'Portfolio drawdown {current_dd:.1%} approaching limit {self.max_drawdown:.1%}',
                'details': {'current_drawdown': current_dd, 'limit': self.max_drawdown}
            })

        # Leverage check
        positions_value = abs(self.portfolio.positions_value)
        leverage = positions_value / portfolio_value if portfolio_value > 0 else 0
        if leverage > self.max_leverage:
            alerts.append({
                'limit_type': 'LEVERAGE',
                'severity': 'CRITICAL',
                'message': f'Gross leverage {leverage:.2f}x exceeds limit {self.max_leverage:.1f}x',
                'details': {'leverage': leverage, 'limit': self.max_leverage}
            })

        # Concentration check
        for symbol, position in self.portfolio.positions.items():
            if position.quantity == 0:
                continue
            weight = abs(position.market_value) / portfolio_value
            if weight > self.max_concentration:
                alerts.append({
                    'limit_type': 'CONCENTRATION',
                    'severity': 'WARNING',
                    'message': f'{symbol} weight {weight:.1%} exceeds concentration limit {self.max_concentration:.1%}',
                    'details': {'symbol': symbol, 'weight': weight, 'limit': self.max_concentration}
                })

        return alerts

    def calculate_portfolio_risk(self) -> Dict[str, float]:
        """
        Calculate portfolio-level risk metrics for reporting.

        Returns:
            Dictionary of risk metrics
        """
        portfolio_value = self.portfolio.total_value

        # Extract equity values from curve
        equity_values = [v for _, v in self.portfolio.equity_curve]

        # Current drawdown
        current_dd = self._current_drawdown()

        # Leverage
        positions_value = abs(self.portfolio.positions_value)
        leverage = positions_value / portfolio_value if portfolio_value > 0 else 0.0

        # Largest position weight
        largest_weight = 0.0
        num_positions = 0
        for position in self.portfolio.positions.values():
            if position.quantity != 0:
                num_positions += 1
                weight = abs(position.market_value) / portfolio_value if portfolio_value > 0 else 0
                largest_weight = max(largest_weight, weight)

        # VaR and CVaR from equity curve returns
        var_95 = 0.0
        var_99 = 0.0
        expected_shortfall_95 = 0.0

        if len(equity_values) > 2:
            arr = np.array(equity_values, dtype=float)
            returns = np.diff(arr) / arr[:-1]
            returns = returns[np.isfinite(returns)]
            if len(returns) > 1:
                var_95 = float(np.percentile(returns, 5))
                var_99 = float(np.percentile(returns, 1))
                tail = returns[returns <= var_95]
                expected_shortfall_95 = float(np.mean(tail)) if len(tail) > 0 else var_95

        return {
            'var_95': var_95,
            'var_99': var_99,
            'expected_shortfall_95': expected_shortfall_95,
            'current_drawdown': current_dd,
            'gross_leverage': leverage,
            'largest_position_weight': largest_weight,
            'num_positions': num_positions,
        }

    def _current_drawdown(self) -> float:
        """Calculate current drawdown from peak equity."""
        equity_values = [v for _, v in self.portfolio.equity_curve]
        if not equity_values:
            return 0.0
        peak = max(equity_values)
        if peak <= 0:
            return 0.0
        current = equity_values[-1]
        return (current - peak) / peak

    def _publish_risk_event(
        self, limit_type: str, severity: str, message: str,
        details: Dict[str, Any]
    ) -> None:
        """Publish a RiskEvent to the event bus."""
        event = RiskEvent(
            timestamp=datetime.now(),
            event_type=EventType.RISK,
            risk_type=limit_type,
            severity=severity,
            message=message,
            details=details,
        )
        self.event_bus.publish(event)
        logger.warning(f"RISK [{severity}] {limit_type}: {message}")
