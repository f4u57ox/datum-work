import { Activity, ScatterChart, Table, Workflow } from "lucide-react";

export const navItems = [
  { href: "/", label: "Datum Work", icon: Activity, description: "Pool work and local DATUM templates" },
  {
    href: "/table",
    label: "Table",
    icon: Table,
    description: "Main view with table and timing chart",
  },
  {
    href: "/timing",
    label: "Timing",
    icon: ScatterChart,
    description: "Full screen pool timing visualization",
  },
  {
    href: "/sankey",
    label: "Sankey",
    icon: Workflow,
    description: "Sankey diagram visualization",
  },
  {
    href: "/infra",
    label: "Infra",
    icon: Activity,
    description: "Realtime Stratum infrastructure metrics",
  },
];
