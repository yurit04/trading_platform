"""
Report generation for backtest results.
Produces text reports, quantstats tearsheets, and orchestrates full report output.
"""
from typing import List, Tuple, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
import logging

import pandas as pd
import yaml

from ..core.event import FillEvent
from ..portfolio.position import Position
from .metrics import PerformanceMetrics
from .visualization import BacktestVisualizer


logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generate comprehensive backtest reports."""

    @staticmethod
    def generate_text_report(results: Dict[str, Any], output_path: str) -> str:
        """
        Generate formatted text summary of all metrics.

        Args:
            results: Dictionary of backtest results from engine
            output_path: Path to save the text report

        Returns:
            The formatted report string
        """
        lines = []
        lines.append('=' * 70)
        lines.append('BACKTEST REPORT')
        lines.append('=' * 70)
        lines.append('')

        # Period info
        lines.append('BACKTEST PERIOD')
        lines.append('-' * 40)
        start = results.get('start_date', '')
        end = results.get('end_date', '')
        if isinstance(start, datetime):
            start = start.strftime('%Y-%m-%d')
        if isinstance(end, datetime):
            end = end.strftime('%Y-%m-%d')
        lines.append(f'  Start Date:          {start}')
        lines.append(f'  End Date:            {end}')
        lines.append(f'  Initial Capital:     ${results.get("initial_capital", 0):>14,.2f}')
        lines.append(f'  Final Value:         ${results.get("final_value", 0):>14,.2f}')
        lines.append('')

        # Return metrics
        lines.append('RETURN METRICS')
        lines.append('-' * 40)
        lines.append(f'  Total Return:        {results.get("total_return", 0):>10.2%}')
        lines.append(f'  CAGR:                {results.get("cagr", 0):>10.2%}')
        lines.append(f'  Volatility (ann.):   {results.get("volatility", 0):>10.2%}')
        lines.append('')

        # Risk metrics
        lines.append('RISK METRICS')
        lines.append('-' * 40)
        lines.append(f'  Sharpe Ratio:        {results.get("sharpe_ratio", 0):>10.2f}')
        lines.append(f'  Sortino Ratio:       {results.get("sortino_ratio", 0):>10.2f}')
        lines.append(f'  Max Drawdown:        {results.get("max_drawdown", 0):>10.2%}')
        lines.append(f'  Calmar Ratio:        {results.get("calmar_ratio", 0):>10.2f}')
        lines.append('')

        # Trade metrics
        lines.append('TRADE METRICS')
        lines.append('-' * 40)
        lines.append(f'  Total Trades:        {results.get("num_trades", 0):>10d}')
        lines.append(f'  Win Rate:            {results.get("win_rate", 0):>10.2%}')
        pf = results.get('profit_factor', 0)
        pf_str = f'{pf:>10.2f}' if pf != float('inf') else '       inf'
        lines.append(f'  Profit Factor:       {pf_str}')
        lines.append(f'  Avg Win:             ${results.get("avg_win", 0):>13,.2f}')
        lines.append(f'  Avg Loss:            ${results.get("avg_loss", 0):>13,.2f}')
        lines.append(f'  Max Consec. Wins:    {results.get("max_consecutive_wins", 0):>10d}')
        lines.append(f'  Max Consec. Losses:  {results.get("max_consecutive_losses", 0):>10d}')
        lines.append(f'  Avg Trade Duration:  {results.get("avg_trade_duration_days", 0):>10.1f} days')
        lines.append('')
        lines.append('=' * 70)

        report = '\n'.join(lines)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            f.write(report)

        logger.info(f"Text report saved to {output_path}")
        return report

    @staticmethod
    def generate_tearsheet(
        equity_curve: List[Tuple[datetime, float]],
        output_path: str
    ) -> None:
        """
        Generate quantstats HTML tearsheet.

        Args:
            equity_curve: List of (timestamp, portfolio_value) tuples
            output_path: Path to save the HTML tearsheet
        """
        try:
            import quantstats as qs

            returns = PerformanceMetrics.daily_returns(equity_curve)
            if returns.empty:
                logger.warning("No daily returns to generate tearsheet")
                return

            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            qs.reports.html(returns, output=output_path, title='Backtest Tearsheet')
            logger.info(f"Quantstats tearsheet saved to {output_path}")

        except ImportError:
            logger.warning("quantstats not installed — skipping tearsheet generation")
        except Exception as e:
            logger.warning(f"Failed to generate quantstats tearsheet: {e}")

    @staticmethod
    def generate_full_report(
        results: Dict[str, Any],
        equity_curve: List[Tuple[datetime, float]],
        trade_history: List[FillEvent],
        positions: Dict[str, 'Position'],
        output_dir: str
    ) -> str:
        """
        Generate complete report suite: charts, tearsheet, text report, YAML results.

        Args:
            results: Dictionary of backtest results
            equity_curve: List of (timestamp, portfolio_value) tuples
            trade_history: List of FillEvent objects
            positions: Dict of symbol to Position
            output_dir: Base output directory

        Returns:
            Path to the output directory
        """
        base = Path(output_dir)
        base.mkdir(parents=True, exist_ok=True)

        # 1. Save YAML results
        yaml_results = {}
        for k, v in results.items():
            if isinstance(v, datetime):
                yaml_results[k] = v.strftime('%Y-%m-%d')
            elif isinstance(v, float) and v == float('inf'):
                yaml_results[k] = 'inf'
            else:
                yaml_results[k] = v

        with open(base / 'results.yaml', 'w') as f:
            yaml.dump(yaml_results, f, default_flow_style=False)

        # 2. Text report
        ReportGenerator.generate_text_report(results, str(base / 'report.txt'))

        # 3. Quantstats tearsheet
        ReportGenerator.generate_tearsheet(equity_curve, str(base / 'tearsheet.html'))

        # 4. Static charts
        initial_capital = results.get('initial_capital', 1_000_000)
        viz = BacktestVisualizer(
            equity_curve=equity_curve,
            trade_history=trade_history,
            positions=positions,
            initial_capital=initial_capital
        )
        charts_dir = str(base / 'charts')
        viz.generate_all_charts(charts_dir)

        # 5. Interactive charts
        interactive_dir = base / 'interactive'
        interactive_dir.mkdir(parents=True, exist_ok=True)
        viz.generate_interactive_report(str(interactive_dir / 'report.html'))

        logger.info(f"Full report generated in {output_dir}")
        return str(base)
