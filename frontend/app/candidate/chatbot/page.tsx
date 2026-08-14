import { PageHeader } from "@/components/page-header";
import { AssistantChat } from "@/components/assistant-chat";

export default function CandidateChatbotPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Assistant Chatbot"
        description="Ask about your application, the hiring process, or company policies."
      />
      <AssistantChat />
    </div>
  );
}
