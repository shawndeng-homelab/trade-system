# ---
# jupyter:
#   jupytext:
#     formats: py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
# ---

# %% [markdown]
# # PMCC research
#
# Explore option-chain selection for a Poor Man's Covered Call: long a ~0.8-delta
# LEAPS call, short a ~0.3-delta near-term call. This notebook uses the same
# `select_by_delta` helper the backtest strategy uses, so the legs validated here are
# the legs a backtest would trade.
#
# Install the research stack first: `uv sync --all-packages --all-groups --extra research`

# %%


from trade_system_strategies.research.analyze import select_leg_summary


# %% [markdown]
# ## Load option instruments from the shared catalog

# %%
# instruments = load_option_instruments(underlying="SPY")
# instruments[:5]

# %% [markdown]
# ## Validate leg selection
#
# Replace with real chain strikes/deltas pulled from the catalog.

# %%
candidates = [(400.0, 0.82), (410.0, 0.65), (420.0, 0.50), (430.0, 0.35), (440.0, 0.22)]
targets = [0.8, 0.3]  # LEAPS delta, short-call delta

# %%
select_leg_summary(candidates, targets)
