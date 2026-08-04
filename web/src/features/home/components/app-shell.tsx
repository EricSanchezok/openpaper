"use client";

import {
  BookStack,
  ChatBubbleEmpty,
  ChatPlusIn,
  Folder,
  LogOut,
  Menu,
  NavArrowDown,
  Settings,
  SidebarCollapse,
  SidebarExpand,
} from "iconoir-react";
import Link from "next/link";
import type { Route } from "next";
import { useTranslations } from "next-intl";
import * as React from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  IconButton,
  Sheet,
  SheetContent,
  SheetTitle,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui";
import { Icon, type IconGlyph } from "@/design-system/icons/icon";
import { useTheme } from "@/design-system/theme/theme-provider";
import type { Actor } from "@/features/authentication";
import type { components } from "@/lib/api/generated/schema";
import { cn } from "@/lib/utilities/cn";

type ConversationSummary = components["schemas"]["ConversationSummaryResponse"];

function SidebarControl({
  collapsed,
  label,
  glyph,
  active,
  href,
  disabled,
  onSelect,
}: {
  collapsed: boolean;
  label: string;
  glyph: IconGlyph;
  active?: boolean;
  href?: string;
  disabled?: boolean;
  onSelect?: () => void;
}) {
  const control = href ? (
    <Link
      aria-current={active ? "page" : undefined}
      aria-label={collapsed ? label : undefined}
      className={cn(
        "hover:bg-hover flex h-11 items-center gap-2.5 rounded-[var(--radius-md)] text-[13px] font-medium transition-colors focus-visible:ring-2 focus-visible:ring-[var(--color-focus-ring)] focus-visible:outline-none",
        collapsed ? "w-11 justify-center" : "w-full px-2.5",
        active && "bg-pressed",
      )}
      href={href as Route}
      onClick={onSelect}
    >
      <Icon glyph={glyph} size={20} tone={active ? "primary" : "secondary"} />
      {!collapsed && <span className="truncate">{label}</span>}
    </Link>
  ) : (
    <button
      aria-disabled={disabled || undefined}
      aria-label={collapsed ? label : undefined}
      className={cn(
        "flex h-11 items-center gap-2.5 rounded-[var(--radius-md)] text-[13px] font-medium focus-visible:ring-2 focus-visible:ring-[var(--color-focus-ring)] focus-visible:outline-none",
        collapsed ? "w-11 justify-center" : "w-full px-2.5",
        disabled ? "text-muted cursor-not-allowed" : "hover:bg-hover",
      )}
      onClick={disabled ? undefined : onSelect}
      type="button"
    >
      <Icon glyph={glyph} size={20} tone="secondary" />
      {!collapsed && <span className="truncate">{label}</span>}
    </button>
  );

  if (!collapsed) return control;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{control}</TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  );
}

function ConversationGroup({
  title,
  items,
  emptyLabel,
  activeConversationId,
  onSelect,
}: {
  title: string;
  items: ConversationSummary[];
  emptyLabel: string;
  activeConversationId?: string;
  onSelect?: () => void;
}) {
  return (
    <section className="grid gap-0.5">
      <div className="text-secondary flex h-7 items-center px-2 text-xs font-medium">
        {title}
      </div>
      {items.length === 0 ? (
        <p className="text-secondary px-2 py-1 text-xs leading-5">
          {emptyLabel}
        </p>
      ) : (
        items.map((conversation) => (
          <Link
            aria-current={
              activeConversationId === conversation.id ? "page" : undefined
            }
            className={cn(
              "hover:bg-hover flex h-9 min-w-0 items-center gap-2 rounded-[var(--radius-md)] px-2 text-[13px] focus-visible:ring-2 focus-visible:ring-[var(--color-focus-ring)] focus-visible:outline-none",
              activeConversationId === conversation.id && "bg-pressed",
            )}
            href={`/?conversation=${conversation.id}`}
            key={conversation.id}
            onClick={onSelect}
          >
            {conversation.pinned_at && (
              <Icon glyph={ChatBubbleEmpty} size={20} tone="secondary" />
            )}
            <span className="min-w-0 flex-1 truncate">
              {conversation.title}
            </span>
            {conversation.scope_label && (
              <span className="text-secondary max-w-[4.5rem] truncate text-[11px]">
                {conversation.scope_label}
              </span>
            )}
          </Link>
        ))
      )}
    </section>
  );
}

function AccountMenu({
  actor,
  collapsed,
  signingOut,
  onSignOut,
}: {
  actor: Actor;
  collapsed: boolean;
  signingOut: boolean;
  onSignOut: () => Promise<void>;
}) {
  const t = useTranslations("Home");
  const { preference, setColorSchemePreference } = useTheme();
  const name =
    actor.display_name?.trim() || actor.email.split("@")[0] || actor.email;
  const initial = name.slice(0, 1).toUpperCase();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          aria-label={t("account.openMenu")}
          className={cn(
            "hover:bg-hover flex h-[52px] items-center rounded-[var(--radius-md)] px-2 focus-visible:ring-2 focus-visible:ring-[var(--color-focus-ring)] focus-visible:outline-none",
            collapsed ? "w-11 justify-center" : "w-full gap-2.5",
          )}
          type="button"
        >
          <span className="bg-pressed grid size-7 shrink-0 place-items-center rounded-full text-xs font-medium">
            {initial}
          </span>
          {!collapsed && (
            <>
              <span className="min-w-0 flex-1 truncate text-left text-[13px] font-medium">
                {name}
              </span>
              <Icon glyph={NavArrowDown} size={16} tone="secondary" />
            </>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align={collapsed ? "start" : "center"}
        className="w-60"
        side="top"
      >
        <DropdownMenuLabel className="grid gap-0.5 px-2 py-2">
          <span className="text-foreground truncate text-sm">{name}</span>
          <span className="text-muted truncate font-normal">{actor.email}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem disabled>
          <Icon glyph={Settings} size={16} tone="secondary" />
          {t("account.settings")}
        </DropdownMenuItem>
        <DropdownMenuGroup>
          <DropdownMenuLabel>{t("account.appearance")}</DropdownMenuLabel>
          <DropdownMenuRadioGroup
            onValueChange={(value) =>
              setColorSchemePreference(value as "light" | "dark" | "system")
            }
            value={preference}
          >
            <DropdownMenuRadioItem value="light">
              {t("account.light")}
            </DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="dark">
              {t("account.dark")}
            </DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="system">
              {t("account.system")}
            </DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          disabled={signingOut}
          onSelect={() => void onSignOut()}
        >
          <Icon glyph={LogOut} size={16} tone="secondary" />
          {signingOut ? t("account.signingOut") : t("account.signOut")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function Sidebar({
  actor,
  conversations,
  activeConversationId,
  collapsed,
  signingOut,
  onCollapsedChange,
  onSignOut,
  onSelect,
}: {
  actor: Actor;
  conversations: ConversationSummary[];
  activeConversationId?: string;
  collapsed: boolean;
  signingOut: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  onSignOut: () => Promise<void>;
  onSelect?: () => void;
}) {
  const t = useTranslations("Home");
  const pinned = conversations.filter((item) => item.pinned_at).slice(0, 3);
  const recent = conversations.filter((item) => !item.pinned_at).slice(0, 7);

  return (
    <TooltipProvider delayDuration={250}>
      <aside
        className={cn(
          "border-line bg-sidebar flex h-full shrink-0 flex-col border-r transition-[width] duration-200 motion-reduce:transition-none",
          collapsed ? "w-16 p-2.5" : "w-[248px] p-4",
        )}
      >
        <div
          className={cn(
            "mb-4 flex h-11 items-center",
            collapsed ? "justify-center" : "justify-between",
          )}
        >
          {!collapsed && (
            <Link
              className="text-base font-medium tracking-[-0.003em]"
              href="/"
            >
              Scholens
            </Link>
          )}
          <IconButton
            className="bg-surface border-line hover:bg-hover"
            label={
              collapsed ? t("navigation.expand") : t("navigation.collapse")
            }
            onClick={() => onCollapsedChange(!collapsed)}
            variant="secondary"
          >
            <Icon
              glyph={collapsed ? SidebarExpand : SidebarCollapse}
              size={20}
            />
          </IconButton>
        </div>
        <nav className="grid gap-1" aria-label={t("navigation.openMenu")}>
          <SidebarControl
            active={!activeConversationId}
            collapsed={collapsed}
            glyph={ChatPlusIn}
            href="/"
            label={t("navigation.newChat")}
            onSelect={onSelect}
          />
          <SidebarControl
            collapsed={collapsed}
            disabled
            glyph={BookStack}
            label={`${t("navigation.library")} · ${t("navigation.comingSoon")}`}
          />
          <SidebarControl
            collapsed={collapsed}
            disabled
            glyph={Folder}
            label={`${t("navigation.projects")} · ${t("navigation.comingSoon")}`}
          />
        </nav>
        {!collapsed && (
          <div className="mt-4 min-h-0 flex-1 overflow-y-auto">
            <ConversationGroup
              activeConversationId={activeConversationId}
              emptyLabel={t("sidebar.noPinned")}
              items={pinned}
              onSelect={onSelect}
              title={t("sidebar.pinned")}
            />
            <div className="mt-2">
              <ConversationGroup
                activeConversationId={activeConversationId}
                emptyLabel={t("sidebar.noRecent")}
                items={recent}
                onSelect={onSelect}
                title={t("sidebar.recent")}
              />
            </div>
          </div>
        )}
        {collapsed && <div className="flex-1" />}
        <AccountMenu
          actor={actor}
          collapsed={collapsed}
          onSignOut={onSignOut}
          signingOut={signingOut}
        />
      </aside>
    </TooltipProvider>
  );
}

export function AppShell({
  actor,
  conversations,
  activeConversationId,
  collapsed,
  signingOut,
  onCollapsedChange,
  onSignOut,
  children,
}: {
  actor: Actor;
  conversations: ConversationSummary[];
  activeConversationId?: string;
  collapsed: boolean;
  signingOut: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  onSignOut: () => Promise<void>;
  children: React.ReactNode;
}) {
  const t = useTranslations("Home");
  const [mobileOpen, setMobileOpen] = React.useState(false);

  return (
    <div className="bg-canvas flex h-screen min-h-[36rem] overflow-hidden">
      <div className="hidden lg:block">
        <Sidebar
          activeConversationId={activeConversationId}
          actor={actor}
          collapsed={collapsed}
          conversations={conversations}
          onCollapsedChange={onCollapsedChange}
          onSignOut={onSignOut}
          signingOut={signingOut}
        />
      </div>
      <Sheet onOpenChange={setMobileOpen} open={mobileOpen}>
        <SheetContent
          className="left-0 w-[min(88vw,248px)] border-r border-l-0 p-0"
          closeLabel={t("navigation.closeMenu")}
        >
          <SheetTitle className="sr-only">
            {t("navigation.openMenu")}
          </SheetTitle>
          <Sidebar
            activeConversationId={activeConversationId}
            actor={actor}
            collapsed={false}
            conversations={conversations}
            onCollapsedChange={() => setMobileOpen(false)}
            onSelect={() => setMobileOpen(false)}
            onSignOut={onSignOut}
            signingOut={signingOut}
          />
        </SheetContent>
      </Sheet>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="border-line flex h-14 shrink-0 items-center justify-between border-b px-3 lg:hidden">
          <IconButton
            label={t("navigation.openMenu")}
            onClick={() => setMobileOpen(true)}
            variant="ghost"
          >
            <Icon glyph={Menu} size={20} />
          </IconButton>
          <Link className="text-sm font-semibold" href="/">
            Scholens
          </Link>
          <span aria-hidden className="size-11" />
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
