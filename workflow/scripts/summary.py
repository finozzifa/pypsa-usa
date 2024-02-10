"""Calcualtes summary files

Adapted from PyPSA-Eur summary statistics reporting script 
 - https://github.com/PyPSA/pypsa-eur/blob/master/scripts/make_summary.py
"""

import pypsa 
import pandas as pd
from _helpers import configure_logging
import logging
logger = logging.getLogger(__name__)


### 
# ENERGY SUPLPY
###

def get_energy_total(n: pypsa.Network):
    """Gets energy production totals"""

    def _get_energy_one_port(n: pypsa.Network, c: str) -> pd.DataFrame:
            return (
                c.pnl.p.multiply(n.snapshot_weightings.generators, axis=0)
                .sum()
                .multiply(c.df.sign)
                .groupby(c.df.carrier)
                .sum()
            )
            
    def _get_energy_multi_port(n: pypsa.Network, c: str) -> pd.DataFrame:
        c_energies = pd.Series(0.0, c.df.carrier.unique())
        for port in [col[3:] for col in c.df.columns if col[:3] == "bus"]:
            totals = (
                c.pnl["p" + port]
                .multiply(n.snapshot_weightings.generators, axis=0)
                .sum()
            )
            # remove values where bus is missing (bug in nomopyomo)
            no_bus = c.df.index[c.df["bus" + port] == ""]
            totals.loc[no_bus] = float(
                n.component_attrs[c.name].loc["p" + port, "default"]
            )
            c_energies -= totals.groupby(c.df.carrier).sum()
        return c_energies
    
    energy = []
    for c in n.iterate_components(n.one_port_components | n.branch_components):
        if c.name in ("Generator", "StorageUnit", "Store"):
            e = _get_energy_one_port(n, c)
        elif c.name in ("Link"):
            e = _get_energy_multi_port(n, c)
        else:
            continue
        energy.append(e)
        
    return pd.concat(energy, axis=1)

def get_energy_timeseries(n: pypsa.Network) -> pd.DataFrame:
    """Gets timeseries energy production"""

    def _get_energy_one_port(n: pypsa.Network, c: str) -> pd.DataFrame:
            return (
                c.pnl.p.multiply(n.snapshot_weightings.generators, axis=0)
                .multiply(c.df.sign)
                .T
                .groupby(c.df.carrier)
                .sum()
                .T
            )
            
    def _get_energy_multi_port(n: pypsa.Network, c: str) -> pd.DataFrame:
        c_energies = pd.DataFrame(index=n.snapshots, columns=c.df.carrier.unique()).fillna(0)
        for port in [col[3:] for col in c.df.columns if col[:3] == "bus"]:
            if port == "0": # only track flow in one direction 
                continue
            totals = (
                c.pnl["p" + port]
                .multiply(n.snapshot_weightings.generators, axis=0)
            )
            # remove values where bus is missing (bug in nomopyomo)
            no_bus = c.df.index[c.df["bus" + port] == ""]
            totals.loc[no_bus] = float(
                n.component_attrs[c.name].loc["p" + port, "default"]
            )
            c_energies -= totals.T.groupby(c.df.carrier).sum().T
        return c_energies
    
    energy = []
    for c in n.iterate_components(n.one_port_components | n.branch_components):
        # if c.name in ("Generator", "StorageUnit", "Store"):
        if c.name in ("Generator", "StorageUnit", "Store"):
            e = _get_energy_one_port(n, c)
        elif c.name in ("Link"):
            e = _get_energy_multi_port(n, c)
        else:
            continue
        energy.append(e)
        
    return pd.concat(energy, axis=1)

### 
# ENERGY DEMAND
###

def get_demand_timeseries(n: pypsa.Network) -> pd.DataFrame:
    """Gets timeseries energy demand"""
    return pd.DataFrame(n.loads_t.p.sum(1)).rename(columns={0:"Demand"})

### 
# ENERGY CAPACITY
###

def get_capacity_base(n: pypsa.Network) -> pd.DataFrame:
    """Gets starting capacities
    
    NOTE: Link capacities are grouped by both bus0 and bus1!!
    It is up to the user to filter this by bus on the returned dataframe 
    """
    totals=[]
    for c in n.iterate_components(n.one_port_components | n.branch_components):
        if c.name in ("Generator", "StorageUnit"):
            totals.append((c.df.p_nom).groupby(by=[c.df.bus, c.df.carrier]).sum())
        elif c.name == "Link":
            totals.append((c.df.p_nom).groupby(by=[c.df.bus0,c.df.carrier]).sum().rename_axis(index={"bus0":"bus"})),
            totals.append((c.df.p_nom).groupby(by=[c.df.bus1,c.df.carrier]).sum().rename_axis(index={"bus1":"bus"}))
    return pd.concat(totals)

def get_capacity_greenfield(n: pypsa.Network, retirement_method = "economic") -> pd.DataFrame:
    """Gets optimal greenfield pnom capacity
    
    NOTE: Link capacities are grouped by both bus0 and bus1!!
    It is up to the user to filter this by bus on the returned dataframe 
    """
    
    def _technical_retirement(c:pypsa.components.Component) -> pd.DataFrame:
        if c.name == "Link":
            # unidirectional links, so only take p0
            return pd.concat(
                [
                    (c.pnl.p0.max()).groupby(by=[c.df.bus0,c.df.carrier]).sum().rename_axis(index={"bus0":"bus"}),
                    (c.pnl.p0.max()).groupby(by=[c.df.bus1,c.df.carrier]).sum().rename_axis(index={"bus1":"bus"})
                ]
            ) 
        else:
            return (c.pnl.p.max()).groupby(by=[c.df.bus, c.df.carrier]).sum()
    
    def _economic_retirement(c:pypsa.components.Component) -> pd.DataFrame:
        if c.name == "Link":
            return pd.concat(
                [
                    (c.df.p_nom_opt).groupby(by=[c.df.bus0,c.df.carrier]).sum().rename_axis(index={"bus0":"bus"}),
                    (c.df.p_nom_opt).groupby(by=[c.df.bus1,c.df.carrier]).sum().rename_axis(index={"bus1":"bus"})
                ]
            )
        else:
            return (c.df.p_nom_opt).groupby(by=[c.df.bus, c.df.carrier]).sum()
    
    totals=[]
    if retirement_method == "technical":
        for c in n.iterate_components(n.one_port_components | n.branch_components):
            if c.name in ("Generator", "StorageUnit", "Link"):
                totals.append(_technical_retirement(c))
        return pd.concat(totals)
    elif retirement_method == "economic":
        for c in n.iterate_components(n.one_port_components | n.branch_components):
            if c.name in ("Generator", "StorageUnit", "Link"):
                totals.append(_economic_retirement(c))
        return pd.concat(totals)
    else:
        logger.error(f"Retirement method must be one of 'technical' or 'economic'. Recieved {retirement_method}.")
        raise NotImplementedError

def get_capacity_brownfield(n: pypsa.Network, retirement_method = "economic") -> pd.DataFrame:
    """Gets optimal brownfield pnom capacity
    
    NOTE: Link capacities are grouped by both bus0 and bus1!!
    It is up to the user to filter this by bus on the returned dataframe 
    """
    
    def _technical_retirement(c:pypsa.components.Component) -> pd.DataFrame:
        if c.name == "Link":
            return pd.concat(
                [
                    (c.df.p_nom_opt).groupby(by=[c.df.bus0,c.df.carrier]).sum().rename_axis(index={"bus0":"bus"}),
                    (c.df.p_nom_opt).groupby(by=[c.df.bus1,c.df.carrier]).sum().rename_axis(index={"bus1":"bus"})
                ]
            )
        else:
            return (c.df.p_nom_opt).groupby(by=[c.df.bus, c.df.carrier]).sum()
    
    def _economic_retirement(c:str) -> pd.DataFrame:
        if c.name == "Link":
            return pd.concat(
                [
                    (c.df.p_nom_opt).groupby(by=[c.df.bus0,c.df.carrier]).sum().rename_axis(index={"bus0":"bus"}),
                    (c.df.p_nom_opt).groupby(by=[c.df.bus1,c.df.carrier]).sum().rename_axis(index={"bus1":"bus"})
                ]
            )
        else:
            return (c.df.p_nom_opt).groupby(by=[c.df.bus, c.df.carrier]).sum()
    
    totals = []
    if retirement_method == "technical":
        if c.name in ("Generator", "StorageUnit", "Link"):
                totals.append(_technical_retirement(c))
        return pd.concat(totals)
    elif retirement_method == "economic":
        for c in n.iterate_components(n.one_port_components | n.branch_components):
            if c.name in ("Generator", "StorageUnit", "Link"):
                totals.append(_economic_retirement(c))
        return pd.concat(totals)
    else:
        logger.error(f"Retirement method must be one of 'technical' or 'economic'. Recieved {retirement_method}.")
        raise NotImplementedError

### 
# COSTS
###

def get_operational_costs(n: pypsa.Network) -> pd.DataFrame:
    
    def _get_energy_one_port(c: pypsa.components.Component) -> pd.DataFrame:
        return c.pnl.p.abs()
        
    def _get_energy_multi_port(c: pypsa.components.Component) -> pd.DataFrame:
        return c.pnl.p0.abs()
    
    totals = []
    for c in n.iterate_components(n.one_port_components | n.branch_components):
        if c.name in ("Generator", "StorageUnit", "Store"):
            production = _get_energy_one_port(c)
        elif c.name in ("Link"):
            production = _get_energy_multi_port(c)
        else:
            continue
        
        marginal_cost = c.pnl.marginal_cost
        marginal_cost_static = {}
        for item in [x for x in c.df.index if x not in marginal_cost.columns]:
            marginal_cost_static[item] = [c.df.at[item, "marginal_cost"]] * len(marginal_cost)
        marginal_cost = pd.concat([marginal_cost, pd.DataFrame(marginal_cost_static, index=marginal_cost.index)], axis=1)
        
        opex = (
            (production * marginal_cost)
            .fillna(0)
            .groupby(c.df.carrier, axis=1)
            .sum()
        )

        totals.append(opex)

    return pd.concat(totals, axis=1)

def get_capital_costs(n: pypsa.Network) -> pd.DataFrame:
    
    def _get_new_capacity_MW(c: pypsa.components.Component) -> pd.DataFrame:
        return (c.df.p_nom_opt - c.df.p_nom).map(lambda x: x if x > 0 else 0)
        
    def _get_new_capacity_MWh(c: pypsa.components.Component) -> pd.DataFrame:
        return (c.df.e_nom_opt - c.df.e_nom).map(lambda x: x if x > 0 else 0)
    
    totals = []
    for c in n.iterate_components(n.one_port_components | n.branch_components):
        if c.name in ("Generator", "StorageUnit", "Link"):
            new_capacity = _get_new_capacity_MW(c)
        elif c.name in ("Store"):
            new_capacity = _get_new_capacity_MWh(c)
        else:
            continue
        
        capital_costs = c.df.capital_cost
        
        capex = (
            (new_capacity * capital_costs)
            .fillna(0)
            .groupby(c.df.carrier)
            .sum()
        )

        totals.append(capex)

    return pd.concat(totals)

### 
# EMISSIONS
###

def get_node_emissions_timeseries(n: pypsa.Network) -> pd.DataFrame:
    """Gets timeseries emissions per node"""
    
    totals=[]
    for c in n.iterate_components(n.one_port_components | n.branch_components):
        if c.name in ("Generator"):
            
            # get time series efficiency
            eff = c.pnl.efficiency
            eff_static = {}
            for gen in [x for x in c.df.index if x not in eff.columns]:
                eff_static[gen] = [c.df.at[gen, "efficiency"]] * len(eff)
            eff = pd.concat([eff, pd.DataFrame(eff_static, index=eff.index)], axis=1)
            
            co2_factor = c.df.carrier.map(n.carriers.co2_emissions).fillna(0)
            
            totals.append(
                (
                    c.pnl.p
                    .mul(1/eff)
                    .mul(co2_factor)
                    .groupby(n.generators.bus, axis=1)
                    .sum()
                )
            )
        elif c.name == "Link": # efficiency taken into account by using p0
            
            co2_factor = c.df.carrier.map(n.carriers.co2_emissions).fillna(0)
            
            totals.append(
                (
                    c.pnl.p0
                    .mul(co2_factor)
                    .groupby(n.links.bus0, axis=1)
                    .sum()
                    .rename_axis(index={"bus0":"bus"})
                )
            )
    return pd.concat(totals, axis=1)

def get_tech_emissions_timeseries(n: pypsa.Network) -> pd.DataFrame:
    """Gets timeseries emissions per technology"""

    totals=[]
    for c in n.iterate_components(n.one_port_components | n.branch_components):
        if c.name in ("Generator"):
            
            # get time series efficiency
            eff = c.pnl.efficiency
            eff_static = {}
            for gen in [x for x in c.df.index if x not in eff.columns]:
                eff_static[gen] = [c.df.at[gen, "efficiency"]] * len(eff)
            eff = pd.concat([eff, pd.DataFrame(eff_static, index=eff.index)], axis=1)
            
            co2_factor = c.df.carrier.map(n.carriers.co2_emissions).fillna(0)
            
            totals.append(
                (
                    c.pnl.p
                    .mul(1/eff)
                    .mul(co2_factor)
                    .groupby(n.generators.carrier, axis=1)
                    .sum()
                )
            )
        elif c.name == "Link": # efficiency taken into account by using p0
            
            co2_factor = c.df.carrier.map(n.carriers.co2_emissions).fillna(0)
            
            totals.append(
                (
                    c.pnl.p0
                    .mul(co2_factor)
                    .groupby(n.links.carrier, axis=1)
                    .sum()
                )
            )
    return pd.concat(totals, axis=1)

if __name__ == "__main__":
    if 'snakemake' not in globals():
        from _helpers import mock_snakemake
        snakemake = mock_snakemake(
            'plot_figures', 
            interconnect='texas',
            clusters=40,
            ll='v1.25',
            opts='Co2L1.25',
            sector="E"
        )
    configure_logging(snakemake)
    
    n = pypsa.Network(snakemake.input.network)
    # get_energy_total(n)
    # get_energy_timeseries(n)
    
    