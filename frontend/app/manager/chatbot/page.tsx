import { KnowledgeChat } from "@/components/knowledge-chat";

export default function ManagerChatbotPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">HR Policy Chatbot</h1>
        <p className="mt-0.5 text-sm text-gray-500">
          Ask questions about HR policy and get answers grounded in the indexed knowledge base.
        </p>
      </div>
      <KnowledgeChat />
    </div>
  );
}
