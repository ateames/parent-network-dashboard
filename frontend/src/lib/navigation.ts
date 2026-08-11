export type NavItem = {
  href: string;
  label: string;
};

/** Primary app routes. */
export const NAV_ITEMS: NavItem[] = [
  { href: "/overview", label: "Overview" },
  { href: "/live", label: "Live" },
  { href: "/people", label: "People" },
  { href: "/devices", label: "Devices" },
  { href: "/findings", label: "Findings" },
  { href: "/review", label: "Review" },
  { href: "/health/sources", label: "Source Health" },
  { href: "/health/system", label: "System Health" },
  { href: "/settings", label: "Settings" },
];
