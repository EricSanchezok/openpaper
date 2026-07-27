"use client"

import Link from "next/link";
import {
    SidebarGroup,
    SidebarGroupContent,
    SidebarMenu,
    SidebarMenuButton,
    SidebarMenuItem,
} from "@/components/ui/sidebar";
import { Badge } from "@/components/ui/badge";
import { CollapsibleSidebarMenu } from "../CollapsibleSidebarMenu";
import { navItems } from "./navItems";
import { User } from "@/lib/auth";
import { Conversation, PaperItem, Project } from "@/lib/schema";

interface SidebarNavProps {
    user: User | null;
    papers: PaperItem[];
    conversations: Conversation[];
    projects: Project[];
}

function getConversationUrl(conversation: Conversation): string {
    if (
        conversation.conversable_type === "project"
        && conversation.conversable_id
    ) {
        return `/projects/${conversation.conversable_id}/conversations/${conversation.id}`;
    }
    if (
        conversation.conversable_type === "paper"
        && conversation.conversable_id
    ) {
        const query = new URLSearchParams({
            rsf: "chat",
            conversation: conversation.id,
        });
        return `/paper/${conversation.conversable_id}?${query.toString()}`;
    }
    return `/understand?id=${conversation.id}`;
}

export function SidebarNav({ user, papers, conversations, projects }: SidebarNavProps) {
    return (
        <SidebarGroup>
            <SidebarGroupContent>
                <SidebarMenu>
                    {navItems.map((item) => {
                        if (item.title === "Library") {
                            return (
                                <CollapsibleSidebarMenu
                                    key={item.title}
                                    title={item.title}
                                    icon={item.icon}
                                    url={item.url}
                                    items={papers}
                                    getItemUrl={(paper) => `/paper/${paper.id}`}
                                    viewAllUrl="/papers"
                                    viewAllText="View all papers"
                                    defaultOpen={true}
                                />
                            )
                        }
                        if (item.title === "Ask") {
                            return (
                                <CollapsibleSidebarMenu
                                    key={item.title}
                                    title={item.title}
                                    icon={item.icon}
                                    url={item.url}
                                    items={conversations}
                                    getItemUrl={getConversationUrl}
                                    getItemMeta={(conversation) =>
                                        conversation.scope_label
                                    }
                                    viewAllUrl="/understand/past"
                                    viewAllText="View all chats"
                                    defaultOpen={false}
                                />
                            )
                        }
                        if (item.title === "Projects") {
                            return (
                                <CollapsibleSidebarMenu
                                    key={item.title}
                                    title={item.title}
                                    icon={item.icon}
                                    url={item.url}
                                    items={projects}
                                    getItemUrl={(project) => `/projects/${project.id}`}
                                    getItemName={(project) => project.title}
                                    viewAllUrl="/projects"
                                    viewAllText="View all projects"
                                    defaultOpen={false}
                                    maxItems={3}
                                />
                            )
                        }
                        return (
                            <SidebarMenuItem key={item.title}>
                                <SidebarMenuButton asChild>
                                    <Link href={item.requiresAuth && !user ? "/login" : item.url}>
                                        <item.icon />
                                        <span>{item.title}</span>
                                        {item.isNew && (
                                            <Badge className="ml-auto text-[10px] px-1.5 py-0 bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-blue-900">
                                                New
                                            </Badge>
                                        )}
                                    </Link>
                                </SidebarMenuButton>
                            </SidebarMenuItem>
                        )
                    })}
                </SidebarMenu>
            </SidebarGroupContent>
        </SidebarGroup>
    )
}
