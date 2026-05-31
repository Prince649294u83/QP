import { useEffect, useState } from "react";
import {
  BookOpen,
  Brain,
  ChevronLeft,
  ChevronRight,
  FileText,
  GraduationCap,
  History,
  Home,
  LayoutDashboard,
  LogOut,
  Moon,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Sun,
  Upload,
  BarChart3,
  Bell,
  PanelLeftClose,
  PanelLeft,
  ChevronDown,
} from "lucide-react";
import { Link, useLocation } from "wouter";
import { motion, AnimatePresence } from "framer-motion";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useTheme } from "next-themes";

interface LayoutProps {
  children: React.ReactNode;
}

interface NavItem {
  href: string;
  icon: typeof Home;
  label: string;
  badge?: string;
  group: string;
}

const navItems: NavItem[] = [
  { href: "/", icon: LayoutDashboard, label: "Dashboard", group: "main" },
  { href: "/subjects", icon: GraduationCap, label: "Subjects", group: "main" },
  { href: "/upload", icon: Upload, label: "Upload Center", group: "main" },
  { href: "/knowledge", icon: BookOpen, label: "Knowledge Base", group: "main" },
  { href: "/questions", icon: FileText, label: "Question Bank", group: "main" },
  { href: "/generate", icon: Sparkles, label: "AI Studio", group: "generate" },
  { href: "/history", icon: History, label: "Paper History", group: "generate" },
  { href: "/review", icon: ShieldCheck, label: "Review Center", group: "review" },
  { href: "/analytics", icon: BarChart3, label: "Analytics", group: "review" },
  { href: "/settings", icon: Settings, label: "Settings", group: "system" },
];

const groupLabels: Record<string, string> = {
  main: "Workspace",
  generate: "Generation",
  review: "Review & Insights",
  system: "System",
};

function SidebarNav({ collapsed, location }: { collapsed: boolean; location: string }) {
  const groups = ["main", "generate", "review", "system"];

  return (
    <nav className="space-y-1 px-2">
      {groups.map((group) => {
        const items = navItems.filter((n) => n.group === group);
        if (!items.length) return null;
        return (
          <div key={group} className="mb-3">
            {!collapsed && (
              <p className="px-3 mb-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/60">
                {groupLabels[group]}
              </p>
            )}
            {items.map((item) => {
              const isActive = location === item.href || (item.href !== "/" && location.startsWith(item.href));
              const inner = (
                <span
                  className={cn(
                    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-150 cursor-pointer",
                    isActive
                      ? "bg-primary/10 text-primary shadow-sm"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  )}
                >
                  <item.icon className={cn("shrink-0", collapsed ? "h-5 w-5" : "h-4 w-4")} />
                  {!collapsed && <span className="truncate">{item.label}</span>}
                  {!collapsed && item.badge && (
                    <span className="ml-auto rounded-full bg-primary/15 px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                      {item.badge}
                    </span>
                  )}
                </span>
              );

              if (collapsed) {
                return (
                  <Tooltip key={item.href} delayDuration={0}>
                    <TooltipTrigger asChild>
                      <Link href={item.href}>{inner}</Link>
                    </TooltipTrigger>
                    <TooltipContent side="right" className="text-xs">
                      {item.label}
                    </TooltipContent>
                  </Tooltip>
                );
              }

              return (
                <Link key={item.href} href={item.href}>
                  {inner}
                </Link>
              );
            })}
          </div>
        );
      })}
    </nav>
  );
}

/* ------------------------------------------------------------------ */
/*  Breadcrumbs                                                        */
/* ------------------------------------------------------------------ */

function Breadcrumbs({ location }: { location: string }) {
  const segments = location.split("/").filter(Boolean);
  if (!segments.length) return <span className="text-sm font-medium text-foreground">Dashboard</span>;

  const currentNav = navItems.find((n) => n.href === location) ?? navItems.find((n) => n.href !== "/" && location.startsWith(n.href));
  return (
    <div className="flex items-center gap-1.5 text-sm">
      <Link href="/">
        <span className="text-muted-foreground hover:text-foreground transition-colors cursor-pointer">Dashboard</span>
      </Link>
      {currentNav && (
        <>
          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/40" />
          <span className="font-medium text-foreground">{currentNav.label}</span>
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Layout                                                        */
/* ------------------------------------------------------------------ */

export function Layout({ children }: LayoutProps) {
  const [location, setLocation] = useLocation();
  const { theme, setTheme } = useTheme();
  const [collapsed, setCollapsed] = useState(false);
  const hasToken = Boolean(localStorage.getItem("access_token"));

  useEffect(() => {
    if (!hasToken && location !== "/login") {
      setLocation("/login");
    }
  }, [hasToken, location, setLocation]);

  const handleLogout = () => {
    localStorage.removeItem("access_token");
    setLocation("/login");
  };

  if (location === "/login") {
    return <div className="min-h-screen bg-background">{children}</div>;
  }

  if (!hasToken) {
    return <div className="min-h-screen bg-background" />;
  }

  return (
    <div className="flex h-screen bg-background overflow-hidden">
      {/* ---- Sidebar ---- */}
      <motion.aside
        className="hidden md:flex flex-col border-r bg-card/80 backdrop-blur-sm shrink-0"
        animate={{ width: collapsed ? 64 : 256 }}
        transition={{ duration: 0.2, ease: "easeInOut" }}
      >
        {/* Logo */}
        <div className={cn("flex items-center gap-3 shrink-0", collapsed ? "justify-center p-4" : "px-5 py-5")}>
          <div className="h-9 w-9 rounded-xl bg-gradient-to-br from-primary to-primary/70 flex items-center justify-center shadow-md shrink-0">
            <GraduationCap className="h-5 w-5 text-primary-foreground" />
          </div>
          <AnimatePresence>
            {!collapsed && (
              <motion.div
                initial={{ opacity: 0, width: 0 }}
                animate={{ opacity: 1, width: "auto" }}
                exit={{ opacity: 0, width: 0 }}
                className="overflow-hidden"
              >
                <h1 className="font-bold text-base leading-tight tracking-tight text-foreground whitespace-nowrap">QPGen</h1>
                <p className="text-[9px] text-muted-foreground font-semibold uppercase tracking-[0.15em] whitespace-nowrap">DSATM Academic Portal</p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <Separator className="opacity-50" />

        {/* Nav */}
        <ScrollArea className="flex-1 py-3">
          <SidebarNav collapsed={collapsed} location={location} />
        </ScrollArea>

        {/* Collapse toggle */}
        <Separator className="opacity-50" />
        <div className={cn("p-2 flex", collapsed ? "justify-center" : "justify-end px-3")}>
          <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground" onClick={() => setCollapsed(!collapsed)}>
            {collapsed ? <PanelLeft className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          </Button>
        </div>

        {/* User */}
        <Separator className="opacity-50" />
        <div className={cn("p-3", collapsed && "flex justify-center")}>
          {collapsed ? (
            <Tooltip delayDuration={0}>
              <TooltipTrigger asChild>
                <div className="h-9 w-9 rounded-full bg-primary/10 flex items-center justify-center cursor-pointer">
                  <span className="text-xs font-bold text-primary">F</span>
                </div>
              </TooltipTrigger>
              <TooltipContent side="right">Faculty User</TooltipContent>
            </Tooltip>
          ) : (
            <div className="flex items-center gap-3 px-1">
              <div className="h-9 w-9 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                <span className="text-xs font-bold text-primary">F</span>
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-foreground truncate">Faculty</p>
                <p className="text-[11px] text-muted-foreground truncate">Computer Science</p>
              </div>
              <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0 text-muted-foreground" onClick={handleLogout} title="Logout">
                <LogOut className="h-3.5 w-3.5" />
              </Button>
            </div>
          )}
        </div>
      </motion.aside>

      {/* ---- Main content ---- */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Header */}
        <header className="h-14 border-b bg-card/60 backdrop-blur-sm flex items-center justify-between px-5 shrink-0">
          {/* Mobile logo */}
          <div className="flex items-center gap-2 md:hidden">
            <div className="h-8 w-8 rounded-lg bg-primary flex items-center justify-center">
              <GraduationCap className="h-4 w-4 text-primary-foreground" />
            </div>
            <span className="font-bold text-foreground">QPGen</span>
          </div>

          {/* Breadcrumbs */}
          <div className="hidden md:block">
            <Breadcrumbs location={location} />
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground">
              <Search className="h-4 w-4" />
            </Button>
            <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground relative">
              <Bell className="h-4 w-4" />
              <span className="absolute top-1 right-1 h-2 w-2 rounded-full bg-primary" />
            </Button>
            <Separator orientation="vertical" className="h-5 mx-1 opacity-40" />
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 text-muted-foreground"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              <Sun className="h-4 w-4 rotate-0 scale-100 transition-transform dark:-rotate-90 dark:scale-0" />
              <Moon className="absolute h-4 w-4 rotate-90 scale-0 transition-transform dark:rotate-0 dark:scale-100" />
              <span className="sr-only">Toggle theme</span>
            </Button>
          </div>
        </header>

        {/* Page */}
        <main className="flex-1 overflow-y-auto bg-muted/20">
          <div className="p-5 md:p-7 max-w-[1440px] mx-auto">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
