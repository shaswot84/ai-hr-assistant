"use client";

import { PageHeader } from "@/components/page-header";
import { AssistantChat } from "@/components/assistant-chat";
import { useSidebar } from "@/components/sidebar-provider";

/**
 * Shell for the chatbot pages (employee / candidate / manager). With the
 * portal sidebar open it shows the standard page header above the chat;
 * when the sidebar is collapsed it drops the header so the chat fills the
 * whole content area, ChatGPT-style.
 */
export function ChatbotPage({
  title,
  description,
  meta,
}: {
  title: string;
  description: string;
  meta?: React.ReactNode;
}) {
  const { collapsed } = useSidebar();

  if (collapsed) {
    return <AssistantChat />;
  }

  return (
    <div className="space-y-6">
      <PageHeader title={title} description={description} meta={meta} />
      <AssistantChat />
    </div>
  );
}
