---
title: Welcome
---

# German Installed Power Capacities (MaStR)

This book explores installed electricity generation and storage capacity in
Germany, based on the Marktstammdatenregister (MaStR) — the German Federal
Network Agency's public register of every power/gas unit in the country.

## About

The pipeline downloads renewable generation and storage units (wind, solar,
biomass, hydro, geothermal/mine-gas/pressure-relaxation, and electricity
storage) via the [open-mastr](https://github.com/OpenEnergyPlatform/open-MaStR)
package, maps every unit to a German NUTS3 region (with offshore wind split
into two synthetic North Sea / Baltic Sea regions, since it falls outside the
NUTS grid), and builds an annual panel of installed capacity so that changes
over time can be analyzed alongside their regional distribution.

## How to read this book

The chapters are structured as executed notebooks. Each notebook corresponds
to a pipeline script in `pipeline/` that was run by DVC.
