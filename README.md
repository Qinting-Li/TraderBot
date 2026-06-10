# TraderBot

TraderBot is a modular trading automation system that bridges Discord-based trading signals with Bitget futures execution. It is designed to monitor selected Discord channels, transform unstructured natural-language trade messages into structured trading instructions, validate each signal through configurable risk-management rules, and route approved orders to the Bitget API when live execution is explicitly enabled.

The system is built with a safety-first execution model. By default, TraderBot operates in dry-run mode, allowing users to audit signal parsing, inspect execution decisions, validate risk parameters, and review logs without placing real orders. Live trading requires an explicit configuration switch and valid exchange credentials, reducing the risk of accidental execution during development or testing.

## Project Features

* **Discord-Based Signal Ingestion**: Monitors configured Discord channels or threads and processes incoming messages as potential trading signals.
* **Structured Signal Extraction**: Parses unstructured text into normalized trade objects, including trading symbol, market direction, entry price, stop-loss level, take-profit targets, and parser confidence.
* **Confidence-Aware Filtering**: Rejects ambiguous or incomplete signals that fall below a configurable confidence threshold.
* **Risk-Governed Execution Pipeline**: Applies pre-trade validation before execution, including per-trade risk limits, leverage caps, notional exposure limits, and stop-loss-based position sizing.
* **Dry-Run First Architecture**: Simulates trade execution and records decision logs by default, enabling safer testing, debugging, and strategy validation.
* **Bitget Futures API Integration**: Supports optional live futures order submission through Bitget REST API credentials when live trading is deliberately enabled.
* **Per-Symbol Cooldown Control**: Prevents duplicate or excessive execution on the same symbol within a configurable time window.
* **Environment-Driven Configuration**: Uses environment variables for Discord credentials, exchange API keys, risk parameters, channel selection, logging level, and runtime behavior.
* **Modular Python Design**: Separates configuration, message parsing, risk calculation, exchange communication, trade execution, Discord connectivity, and application startup into independent components.
* **Test-Covered Core Logic**: Provides unit tests for key components such as signal parsing and risk calculation to support maintainability and regression checking.
* **Security-Conscious Repository Structure**: Avoids hardcoded secrets and provides `.env.example`, `.gitignore`, and dependency files suitable for public repository release.

## Risk Disclaimer

TraderBot is automation software for technical experimentation and workflow automation. It does not provide financial advice, investment recommendations, or guaranteed trading performance. Live trading should only be enabled after independent code review, controlled testing, restricted API-key configuration, and acceptance of all exchange, liquidity, and market risks.
