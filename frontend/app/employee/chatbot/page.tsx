import { KnowledgeChat } from "@/components/knowledge-chat";

export default function EmployeeChatbotPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">HR Policy Chatbot</h1>
        <p className="mt-0.5 text-sm text-gray-500">
          Ask about leave, benefits, HR policy, and more — grounded in the company knowledge base.
        </p>
      </div>
      <KnowledgeChat />
    </div>
  );
}
