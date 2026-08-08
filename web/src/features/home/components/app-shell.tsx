"use client";

import {
  BookStack,
  ChatBubbleEmpty,
  ChatPlusIn,
  Folder,
  LogOut,
  Menu,
  NavArrowDown,
  NavArrowRight,
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
  keyboardFocusRing,
  SearchField,
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
import type { ReasoningLevel } from "./research-composer";
import { useMobileKeyboard } from "../hooks/use-mobile-keyboard";

type ConversationSummary = components["schemas"]["ConversationSummaryResponse"];

function actorName(actor: Actor) {
  return actor.display_name?.trim() || actor.email.split("@")[0] || actor.email;
}

function SidebarControl({
  collapsed,
  label,
  glyph,
  active,
  href,
  disabled,
  disabledHint,
  onSelect,
}: {
  collapsed: boolean;
  label: string;
  glyph: IconGlyph;
  active?: boolean;
  href?: string;
  disabled?: boolean;
  disabledHint?: string;
  onSelect?: () => void;
}) {
  const accessibleLabel =
    disabled && disabledHint ? `${label}. ${disabledHint}` : label;
  const control = href ? (
    <Link
      aria-current={active ? "page" : undefined}
      aria-label={collapsed ? accessibleLabel : undefined}
      className={cn(
        "text-ui hover:bg-hover flex h-11 items-center gap-2.5 rounded-[var(--radius-md)] font-medium transition-colors",
        keyboardFocusRing,
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
      aria-label={disabled || collapsed ? accessibleLabel : undefined}
      className={cn(
        "text-ui flex h-11 items-center gap-2.5 rounded-[var(--radius-md)] font-medium",
        keyboardFocusRing,
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

  if (!collapsed && !disabled) return control;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{control}</TooltipTrigger>
      <TooltipContent side="right">
        {disabled && disabledHint ? `${label} · ${disabledHint}` : label}
      </TooltipContent>
    </Tooltip>
  );
}

function ConversationGroup({
  title,
  items,
  activeConversationId,
  onSelect,
}: {
  title: string;
  items: ConversationSummary[];
  activeConversationId?: string;
  onSelect?: () => void;
}) {
  if (items.length === 0) return null;

  return (
    <section className="grid gap-0.5">
      <div className="text-secondary flex h-7 items-center px-2 text-xs font-medium">
        {title}
      </div>
      {items.map((conversation) => (
        <Link
          aria-current={
            activeConversationId === conversation.id ? "page" : undefined
          }
          className={cn(
            "text-ui hover:bg-hover flex h-9 min-w-0 items-center gap-2 rounded-[var(--radius-md)] px-2",
            keyboardFocusRing,
            activeConversationId === conversation.id && "bg-pressed",
          )}
          href={`/?conversation=${conversation.id}`}
          key={conversation.id}
          onClick={onSelect}
        >
          {conversation.pinned_at && (
            <Icon glyph={ChatBubbleEmpty} size={20} tone="secondary" />
          )}
          <span className="min-w-0 flex-1 truncate">{conversation.title}</span>
          {conversation.scope_label && (
            <span className="text-caption text-secondary max-w-[4.5rem] truncate">
              {conversation.scope_label}
            </span>
          )}
        </Link>
      ))}
    </section>
  );
}

function AccountMenu({
  actor,
  collapsed,
  mobile = false,
  signingOut,
  onSignOut,
}: {
  actor: Actor;
  collapsed: boolean;
  mobile?: boolean;
  signingOut: boolean;
  onSignOut: () => Promise<void>;
}) {
  const t = useTranslations("Home");
  const { preference, setColorSchemePreference } = useTheme();
  const name = actorName(actor);
  const initial = name.slice(0, 1).toUpperCase();

  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <button
          aria-label={t("account.openMenu")}
          className={cn(
            "hover:bg-hover flex items-center rounded-[var(--radius-md)] px-2",
            keyboardFocusRing,
            mobile ? "h-[72px] w-full gap-3" : "h-14",
            collapsed
              ? "ml-auto w-11 justify-center"
              : !mobile && "w-full gap-2.5",
          )}
          type="button"
        >
          <span
            className={cn(
              "bg-pressed grid shrink-0 place-items-center rounded-full font-medium",
              mobile ? "size-10 text-sm" : "size-7 text-xs",
            )}
          >
            {initial}
          </span>
          {!collapsed && (
            <span className="min-w-0 flex-1 text-left">
              <span
                className={cn(
                  "block truncate leading-5 font-medium",
                  mobile ? "text-base" : "text-ui",
                )}
              >
                {name}
              </span>
              <span
                className={cn(
                  "text-secondary block truncate",
                  mobile
                    ? "mt-0.5 text-sm leading-5"
                    : "text-caption leading-4",
                )}
              >
                {actor.email}
              </span>
            </span>
          )}
          {mobile && <Icon glyph={Settings} size={24} tone="secondary" />}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align={collapsed ? "end" : "start"}
        className={cn(
          "shadow-overlay",
          collapsed ? "w-64" : "w-[var(--radix-dropdown-menu-trigger-width)]",
        )}
        side={collapsed ? "right" : "top"}
        sideOffset={collapsed ? 8 : 4}
      >
        <DropdownMenuLabel className="flex items-center gap-2.5 px-2 py-2.5">
          <span className="bg-pressed text-foreground grid size-8 shrink-0 place-items-center rounded-full text-xs font-medium">
            {initial}
          </span>
          <span className="min-w-0">
            <span className="text-foreground block truncate text-sm leading-5">
              {name}
            </span>
            <span className="text-caption text-secondary block truncate leading-4 font-normal">
              {actor.email}
            </span>
          </span>
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

function MobileConversationGroup({
  activeConversationId,
  items,
  onSelect,
  title,
}: {
  activeConversationId?: string;
  items: ConversationSummary[];
  onSelect: () => void;
  title: string;
}) {
  if (items.length === 0) return null;
  return (
    <section className="grid gap-1">
      <h2 className="text-secondary px-3 pt-3 pb-1 text-sm font-medium">
        {title}
      </h2>
      {items.map((conversation) => (
        <Link
          aria-current={
            activeConversationId === conversation.id ? "page" : undefined
          }
          className={cn(
            "hover:bg-hover flex min-h-12 min-w-0 items-center rounded-[var(--radius-lg)] px-3 text-base",
            keyboardFocusRing,
            activeConversationId === conversation.id && "bg-pressed",
          )}
          href={`/?conversation=${conversation.id}`}
          key={conversation.id}
          onClick={onSelect}
        >
          <span className="min-w-0 flex-1 truncate">{conversation.title}</span>
          {conversation.scope_label && (
            <span className="text-secondary ml-3 max-w-20 truncate text-sm">
              {conversation.scope_label}
            </span>
          )}
        </Link>
      ))}
    </section>
  );
}

function MobileNavigation({
  actor,
  conversations,
  activeConversationId,
  signingOut,
  onSignOut,
  onSelect,
}: {
  actor: Actor;
  conversations: ConversationSummary[];
  activeConversationId?: string;
  signingOut: boolean;
  onSignOut: () => Promise<void>;
  onSelect: () => void;
}) {
  const t = useTranslations("Home");
  const [query, setQuery] = React.useState("");
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const matching = normalizedQuery
    ? conversations.filter((conversation) =>
        conversation.title.toLocaleLowerCase().includes(normalizedQuery),
      )
    : conversations;
  const pinned = matching.filter((item) => item.pinned_at).slice(0, 3);
  const recent = matching.filter((item) => !item.pinned_at).slice(0, 12);

  return (
    <aside className="bg-sidebar flex h-full flex-col overflow-hidden pt-[env(safe-area-inset-top)]">
      <div className="flex h-16 shrink-0 items-center px-5 pr-16">
        <Link className="text-xl font-semibold tracking-[-0.015em]" href="/">
          Scholens
        </Link>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3">
        <SearchField
          aria-label={t("navigation.searchConversations")}
          className="bg-subtle h-12 rounded-[var(--radius-lg)] border-transparent text-base"
          onChange={(event) => setQuery(event.currentTarget.value)}
          placeholder={t("navigation.searchConversations")}
          value={query}
        />
        <MobileConversationGroup
          activeConversationId={activeConversationId}
          items={pinned}
          onSelect={onSelect}
          title={t("sidebar.pinned")}
        />
        <MobileConversationGroup
          activeConversationId={activeConversationId}
          items={recent}
          onSelect={onSelect}
          title={t("sidebar.recent")}
        />
        {matching.length === 0 && (
          <p className="text-secondary px-3 py-8 text-center text-sm">
            {normalizedQuery ? t("sidebar.noMatches") : t("sidebar.empty")}
          </p>
        )}
      </div>
      <div className="border-line shrink-0 border-t px-3 pb-[max(var(--space-2),env(safe-area-inset-bottom))]">
        <AccountMenu
          actor={actor}
          collapsed={false}
          mobile
          onSignOut={onSignOut}
          signingOut={signingOut}
        />
      </div>
    </aside>
  );
}

function MobileReasoningMenu({
  onChange,
  value,
}: {
  onChange: (level: ReasoningLevel) => void;
  value: ReasoningLevel;
}) {
  const t = useTranslations("Home.composer");

  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <button
          aria-label={t("reasoningStrengthValue", {
            value: t(value),
          })}
          className={cn(
            "hover:bg-hover active:bg-pressed ml-1 flex min-h-11 min-w-0 items-center gap-1 rounded-[var(--radius-md)] px-2.5 text-left",
            keyboardFocusRing,
          )}
          type="button"
        >
          <span className="truncate text-base font-semibold">{t(value)}</span>
          <Icon glyph={NavArrowDown} size={16} tone="secondary" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        className="w-[min(17rem,calc(100vw-1.5rem))] p-1.5"
        sideOffset={4}
      >
        <DropdownMenuLabel>{t("reasoningStrength")}</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          onValueChange={(nextValue) => onChange(nextValue as ReasoningLevel)}
          value={value}
        >
          {(["standard", "deep"] as const).map((level) => (
            <DropdownMenuRadioItem
              className="min-h-14 items-start py-2.5"
              key={level}
              value={level}
            >
              <span className="min-w-0">
                <span className="text-foreground block font-medium">
                  {t(level)}
                </span>
                <span className="text-secondary mt-0.5 block text-xs leading-4">
                  {t(`${level}Description`)}
                </span>
              </span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function MobileTabBar() {
  const t = useTranslations("Home.navigation");
  const itemClassName = cn(
    "flex min-h-14 min-w-0 flex-1 flex-col items-center justify-center gap-0.5 rounded-[var(--radius-md)] px-1 text-xs font-medium",
    keyboardFocusRing,
  );

  return (
    <nav
      aria-label={t("primary")}
      className="grid h-14 shrink-0 grid-cols-3 lg:hidden"
      data-testid="mobile-tab-bar"
    >
      <Link
        aria-current="page"
        className={cn(itemClassName, "text-foreground")}
        href="/"
      >
        <span
          className="bg-primary grid size-8 place-items-center rounded-full"
          data-selected-indicator
        >
          <Icon glyph={ChatBubbleEmpty} size={20} tone="inverse" />
        </span>
        <span className="font-semibold">{t("ask")}</span>
      </Link>
      <button
        aria-label={`${t("library")}. ${t("comingSoon")}`}
        className={cn(itemClassName, "text-muted")}
        disabled
        type="button"
      >
        <span className="grid size-8 place-items-center">
          <Icon glyph={BookStack} size={24} tone="secondary" />
        </span>
        <span>{t("library")}</span>
      </button>
      <button
        aria-label={`${t("projects")}. ${t("comingSoon")}`}
        className={cn(itemClassName, "text-muted")}
        disabled
        type="button"
      >
        <span className="grid size-8 place-items-center">
          <Icon glyph={Folder} size={24} tone="secondary" />
        </span>
        <span>{t("projects")}</span>
      </button>
    </nav>
  );
}

function MobileBottomDock({
  composer,
  keyboardOpen,
  ref,
}: {
  composer: React.ReactNode;
  keyboardOpen: boolean;
  ref: React.Ref<HTMLDivElement>;
}) {
  return (
    <div
      className={cn(
        "bg-canvas relative z-30 grid shrink-0 gap-1 pr-[calc(var(--space-2)+env(safe-area-inset-right))] pl-[calc(var(--space-2)+env(safe-area-inset-left))] lg:hidden",
        !keyboardOpen && "pb-[env(safe-area-inset-bottom)]",
      )}
      data-keyboard-open={keyboardOpen || undefined}
      data-testid="mobile-bottom-dock"
      ref={ref}
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute right-0 bottom-full left-0 h-5 bg-[linear-gradient(to_top,var(--color-bg-canvas),transparent)]"
      />
      <div className="min-w-0">{composer}</div>
      {!keyboardOpen && <MobileTabBar />}
    </div>
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
          "border-line bg-sidebar flex h-full shrink-0 flex-col overflow-hidden border-r px-3 pt-3 pb-[max(var(--space-1),env(safe-area-inset-bottom))] transition-[width] duration-200 ease-out motion-reduce:transition-none",
          collapsed ? "w-[72px]" : "w-[var(--layout-sidebar)]",
        )}
      >
        <div className="relative mb-4 flex h-11 shrink-0 items-center justify-end">
          <Link
            aria-hidden={collapsed || undefined}
            className={cn(
              "absolute left-1 text-base font-medium tracking-[-0.003em] whitespace-nowrap transition-opacity duration-150 motion-reduce:transition-none",
              collapsed && "pointer-events-none opacity-0",
            )}
            href="/"
            tabIndex={collapsed ? -1 : undefined}
          >
            Scholens
          </Link>
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
        <nav
          className={cn("grid gap-1", collapsed && "justify-items-end")}
          aria-label={t("navigation.openMenu")}
        >
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
            disabledHint={t("navigation.comingSoon")}
            glyph={BookStack}
            label={t("navigation.library")}
          />
          <SidebarControl
            collapsed={collapsed}
            disabled
            disabledHint={t("navigation.comingSoon")}
            glyph={Folder}
            label={t("navigation.projects")}
          />
        </nav>
        {!collapsed && (
          <div className="mt-4 min-h-0 flex-1 overflow-y-auto">
            <ConversationGroup
              activeConversationId={activeConversationId}
              items={pinned}
              onSelect={onSelect}
              title={t("sidebar.pinned")}
            />
            <div className={pinned.length > 0 ? "mt-2" : undefined}>
              <ConversationGroup
                activeConversationId={activeConversationId}
                items={recent}
                onSelect={onSelect}
                title={t("sidebar.recent")}
              />
            </div>
            {pinned.length === 0 && recent.length === 0 && (
              <p className="text-secondary px-2 py-1 text-xs leading-5">
                {t("sidebar.empty")}
              </p>
            )}
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
  reasoningLevel,
  onCollapsedChange,
  onReasoningLevelChange,
  onSignOut,
  mobileComposer,
  mobileKeyboardOverride,
  children,
}: {
  actor: Actor;
  conversations: ConversationSummary[];
  activeConversationId?: string;
  collapsed: boolean;
  signingOut: boolean;
  reasoningLevel: ReasoningLevel;
  onCollapsedChange: (collapsed: boolean) => void;
  onReasoningLevelChange: (level: ReasoningLevel) => void;
  onSignOut: () => Promise<void>;
  mobileComposer?: React.ReactNode;
  mobileKeyboardOverride?: {
    open: boolean;
    viewportHeight?: number;
    viewportOffsetTop?: number;
  };
  children: React.ReactNode;
}) {
  const t = useTranslations("Home");
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const mobileSheetRef = React.useRef<HTMLDivElement>(null);
  const mobileDockRef = React.useRef<HTMLDivElement>(null);
  const mobileKeyboard = useMobileKeyboard(
    mobileDockRef,
    Boolean(mobileComposer),
  );
  const effectiveMobileKeyboard = mobileKeyboardOverride ?? mobileKeyboard;

  return (
    <div
      className="bg-canvas flex h-dvh min-h-0 overflow-hidden antialiased lg:h-screen lg:min-h-[36rem]"
      style={
        effectiveMobileKeyboard.viewportHeight
          ? {
              height: `${effectiveMobileKeyboard.viewportHeight}px`,
              transform: `translateY(${effectiveMobileKeyboard.viewportOffsetTop ?? 0}px)`,
            }
          : undefined
      }
    >
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
          className="left-0 w-full border-0 p-0 focus:outline-none sm:w-[min(92vw,28rem)] sm:border-r"
          closeGlyph={NavArrowRight}
          closeLabel={t("navigation.closeMenu")}
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            mobileSheetRef.current?.focus();
          }}
          ref={mobileSheetRef}
          tabIndex={-1}
        >
          <SheetTitle className="sr-only">
            {t("navigation.openMenu")}
          </SheetTitle>
          <MobileNavigation
            activeConversationId={activeConversationId}
            actor={actor}
            conversations={conversations}
            onSelect={() => setMobileOpen(false)}
            onSignOut={onSignOut}
            signingOut={signingOut}
          />
        </SheetContent>
      </Sheet>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="border-line shrink-0 border-b pt-[env(safe-area-inset-top)] lg:hidden">
          <div className="flex h-16 items-center px-3">
            <IconButton
              label={t("navigation.openMenu")}
              onClick={() => setMobileOpen(true)}
              variant="ghost"
            >
              <Icon glyph={Menu} size={24} />
            </IconButton>
            <MobileReasoningMenu
              onChange={onReasoningLevelChange}
              value={reasoningLevel}
            />
            <Link
              aria-label={t("navigation.newChat")}
              className={cn(
                "hover:bg-hover active:bg-pressed ml-auto grid size-11 place-items-center rounded-[var(--radius-md)]",
                keyboardFocusRing,
              )}
              href="/"
            >
              <Icon glyph={ChatPlusIn} size={24} />
            </Link>
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto" tabIndex={0}>
          {children}
        </main>
        {mobileComposer && (
          <MobileBottomDock
            composer={mobileComposer}
            keyboardOpen={effectiveMobileKeyboard.open}
            ref={mobileDockRef}
          />
        )}
      </div>
    </div>
  );
}
