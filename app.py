import seaborn as sns

# Import data from shared.py
from shared import df

from shiny import App, render, ui

from itables.shiny import DT

# The contents of the first 'page' is a navset with two 'panels'.
page1 = ui.navset_card_underline(
    ui.nav_panel("Plot", ui.output_plot("hist")),
    ui.nav_panel("Table", ui.output_ui("data")),
    footer=ui.input_select(
        "var", "Select variable", choices=["bill_length_mm", "body_mass_g"]
    ),
    title="Penguins data",
)

app_ui = ui.page_navbar(
    ui.nav_spacer(),  # Push the navbar items to the right
    ui.nav_panel("Page 1", page1),
    ui.nav_panel("Page 2", "This is the second 'page'."),
    title="Shiny navigation components",
)


def server(input, output, session):
    @render.plot
    def hist():
        p = sns.histplot(df, x=input.var(), facecolor="#007bc2", edgecolor="white")
        return p.set(xlabel=None)


    @render.ui
    def data():
        dat = df[["species", "island", input.var()]]
        return ui.HTML(DT(dat))


app = App(app_ui, server)
