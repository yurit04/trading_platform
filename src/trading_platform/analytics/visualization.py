"""
Backtest visualization module.
Provides static (matplotlib) and interactive (plotly) charts.
"""
from typing import List, Tuple, Dict, Optional
from datetime import datetime
from pathlib import Path
import logging

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns

from ..core.event import FillEvent
from ..core.enums import OrderSide
from ..portfolio.position import Position
from .metrics import PerformanceMetrics


logger = logging.getLogger(__name__)


class BacktestVisualizer:
    """Generate static and interactive charts from backtest results."""

    def __init__(
        self,
        equity_curve: List[Tuple[datetime, float]],
        trade_history: List[FillEvent],
        positions: Dict[str, Position],
        initial_capital: float = 1_000_000
    ):
        self.equity_curve = equity_curve
        self.trade_history = trade_history
        self.positions = positions
        self.initial_capital = initial_capital

        # Pre-compute common data
        self._timestamps = [t for t, _ in equity_curve]
        self._values = [v for _, v in equity_curve]
        self._round_trips = PerformanceMetrics._compute_round_trip_trades(trade_history)

    # ── Static Charts (matplotlib) ──────────────────────────────────────

    def plot_equity_curve(self, output_path: Optional[str] = None) -> plt.Figure:
        """Plot portfolio value over time with benchmark line at initial capital."""
        fig, ax = plt.subplots(figsize=(12, 6))

        ax.plot(self._timestamps, self._values, linewidth=1.5, label='Portfolio')
        ax.axhline(y=self.initial_capital, color='gray', linestyle='--',
                    alpha=0.7, label='Initial Capital')

        ax.set_title('Equity Curve')
        ax.set_xlabel('Date')
        ax.set_ylabel('Portfolio Value ($)')
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        fig.autofmt_xdate()
        fig.tight_layout()

        if output_path:
            fig.savefig(output_path, dpi=150)
            plt.close(fig)
        return fig

    def plot_drawdown(self, output_path: Optional[str] = None) -> plt.Figure:
        """Plot underwater chart showing drawdown depth over time."""
        dd = PerformanceMetrics.drawdown_series(self.equity_curve)

        fig, ax = plt.subplots(figsize=(12, 4))
        ax.fill_between(dd.index, dd.values, 0, color='red', alpha=0.4)
        ax.plot(dd.index, dd.values, color='red', linewidth=0.8)

        ax.set_title('Drawdown')
        ax.set_xlabel('Date')
        ax.set_ylabel('Drawdown (%)')
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f'{y:.0%}'))
        ax.grid(True, alpha=0.3)
        fig.autofmt_xdate()
        fig.tight_layout()

        if output_path:
            fig.savefig(output_path, dpi=150)
            plt.close(fig)
        return fig

    def plot_monthly_returns(self, output_path: Optional[str] = None) -> plt.Figure:
        """Plot heatmap of monthly returns (months x years)."""
        returns = PerformanceMetrics.daily_returns(self.equity_curve)

        if returns.empty:
            fig, ax = plt.subplots(figsize=(10, 4))
            ax.text(0.5, 0.5, 'Insufficient data', ha='center', va='center')
            if output_path:
                fig.savefig(output_path, dpi=150)
                plt.close(fig)
            return fig

        # Compute monthly returns
        monthly = (1 + returns).resample('ME').prod() - 1
        monthly_df = pd.DataFrame({
            'year': monthly.index.year,
            'month': monthly.index.month,
            'return': monthly.values
        })
        pivot = monthly_df.pivot(index='year', columns='month', values='return')
        pivot.columns = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                         'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][:len(pivot.columns)]

        fig, ax = plt.subplots(figsize=(12, max(3, len(pivot) * 0.6)))
        sns.heatmap(
            pivot * 100, annot=True, fmt='.1f', center=0,
            cmap='RdYlGn', linewidths=0.5, ax=ax,
            cbar_kws={'label': 'Return (%)'}
        )
        ax.set_title('Monthly Returns (%)')
        ax.set_ylabel('Year')
        ax.set_xlabel('Month')
        fig.tight_layout()

        if output_path:
            fig.savefig(output_path, dpi=150)
            plt.close(fig)
        return fig

    def plot_trade_distribution(self, output_path: Optional[str] = None) -> plt.Figure:
        """Plot histogram of individual trade P&L."""
        pnls = [rt['pnl'] for rt in self._round_trips]

        fig, ax = plt.subplots(figsize=(10, 5))

        if pnls:
            colors = ['green' if p > 0 else 'red' for p in sorted(pnls)]
            ax.hist(pnls, bins=min(50, max(10, len(pnls) // 3)),
                    color='steelblue', edgecolor='black', alpha=0.7)
            ax.axvline(x=0, color='black', linestyle='-', linewidth=0.8)

            mean_pnl = np.mean(pnls)
            ax.axvline(x=mean_pnl, color='orange', linestyle='--',
                       label=f'Mean: ${mean_pnl:,.0f}')
            ax.legend()
        else:
            ax.text(0.5, 0.5, 'No round-trip trades', ha='center', va='center',
                    transform=ax.transAxes)

        ax.set_title('Trade P&L Distribution')
        ax.set_xlabel('P&L ($)')
        ax.set_ylabel('Frequency')
        ax.grid(True, alpha=0.3)
        fig.tight_layout()

        if output_path:
            fig.savefig(output_path, dpi=150)
            plt.close(fig)
        return fig

    def plot_positions_summary(self, output_path: Optional[str] = None) -> plt.Figure:
        """Plot horizontal bar chart of final P&L per symbol."""
        symbols = []
        pnls = []
        for symbol, pos in sorted(self.positions.items()):
            symbols.append(symbol)
            pnls.append(pos.total_pnl)

        fig, ax = plt.subplots(figsize=(10, max(4, len(symbols) * 0.5)))

        if symbols:
            colors = ['green' if p >= 0 else 'red' for p in pnls]
            ax.barh(symbols, pnls, color=colors, alpha=0.7, edgecolor='black')
            ax.axvline(x=0, color='black', linewidth=0.8)
        else:
            ax.text(0.5, 0.5, 'No positions', ha='center', va='center',
                    transform=ax.transAxes)

        ax.set_title('P&L by Symbol')
        ax.set_xlabel('Total P&L ($)')
        ax.grid(True, alpha=0.3, axis='x')
        fig.tight_layout()

        if output_path:
            fig.savefig(output_path, dpi=150)
            plt.close(fig)
        return fig

    def generate_all_charts(self, output_dir: str) -> None:
        """Generate all static charts and save as PNGs."""
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)

        self.plot_equity_curve(str(path / 'equity_curve.png'))
        self.plot_drawdown(str(path / 'drawdown.png'))
        self.plot_monthly_returns(str(path / 'monthly_returns.png'))
        self.plot_trade_distribution(str(path / 'trade_distribution.png'))
        self.plot_positions_summary(str(path / 'positions_summary.png'))

        logger.info(f"Saved static charts to {output_dir}")

    # ── Interactive Charts (plotly) ─────────────────────────────────────

    def plot_equity_curve_interactive(self, output_path: Optional[str] = None):
        """Interactive equity curve with hover showing value/date/drawdown."""
        import plotly.graph_objects as go

        dd = PerformanceMetrics.drawdown_series(self.equity_curve)

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=self._timestamps,
            y=self._values,
            mode='lines',
            name='Portfolio Value',
            hovertemplate=(
                'Date: %{x}<br>'
                'Value: $%{y:,.0f}<br>'
                'Drawdown: %{customdata:.2%}<extra></extra>'
            ),
            customdata=dd.values if not dd.empty else [0] * len(self._timestamps)
        ))

        fig.add_hline(
            y=self.initial_capital,
            line_dash='dash',
            line_color='gray',
            annotation_text='Initial Capital'
        )

        fig.update_layout(
            title='Equity Curve',
            xaxis_title='Date',
            yaxis_title='Portfolio Value ($)',
            template='plotly_white',
            hovermode='x unified'
        )

        if output_path:
            fig.write_html(output_path)
        return fig

    def plot_trades_interactive(self, output_path: Optional[str] = None):
        """Scatter plot of trades colored by win/loss."""
        import plotly.graph_objects as go

        if not self._round_trips:
            fig = go.Figure()
            fig.add_annotation(text='No round-trip trades', showarrow=False,
                               xref='paper', yref='paper', x=0.5, y=0.5)
            if output_path:
                fig.write_html(output_path)
            return fig

        wins = [rt for rt in self._round_trips if rt['pnl'] > 0]
        losses = [rt for rt in self._round_trips if rt['pnl'] <= 0]

        fig = go.Figure()

        if wins:
            fig.add_trace(go.Scatter(
                x=[rt['exit_time'] for rt in wins],
                y=[rt['pnl'] for rt in wins],
                mode='markers',
                name='Winning Trades',
                marker=dict(color='green', size=8, symbol='triangle-up'),
                text=[rt['symbol'] for rt in wins],
                hovertemplate='%{text}<br>P&L: $%{y:,.0f}<br>%{x}<extra></extra>'
            ))

        if losses:
            fig.add_trace(go.Scatter(
                x=[rt['exit_time'] for rt in losses],
                y=[rt['pnl'] for rt in losses],
                mode='markers',
                name='Losing Trades',
                marker=dict(color='red', size=8, symbol='triangle-down'),
                text=[rt['symbol'] for rt in losses],
                hovertemplate='%{text}<br>P&L: $%{y:,.0f}<br>%{x}<extra></extra>'
            ))

        fig.add_hline(y=0, line_color='black', line_width=0.5)

        fig.update_layout(
            title='Trade P&L Over Time',
            xaxis_title='Date',
            yaxis_title='P&L ($)',
            template='plotly_white',
            hovermode='closest'
        )

        if output_path:
            fig.write_html(output_path)
        return fig

    def generate_interactive_report(self, output_path: str) -> None:
        """Generate single HTML file with all interactive charts."""
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots

        # Generate individual figures and combine into single HTML
        equity_fig = self.plot_equity_curve_interactive()
        trades_fig = self.plot_trades_interactive()

        html_parts = [
            '<html><head><title>Backtest Interactive Report</title></head><body>',
            '<h1>Backtest Interactive Report</h1>',
            equity_fig.to_html(full_html=False, include_plotlyjs='cdn'),
            '<hr>',
            trades_fig.to_html(full_html=False, include_plotlyjs=False),
            '</body></html>'
        ]

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            f.write('\n'.join(html_parts))

        logger.info(f"Saved interactive report to {output_path}")
