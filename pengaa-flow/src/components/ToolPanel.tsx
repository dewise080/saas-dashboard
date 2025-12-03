import type { DragEvent } from 'react';

interface NodeTemplate {
  type: string;
  label: string;
  icon: string;
  color: string;
  n8nType: string;
}

const nodeTemplates: NodeTemplate[] = [
  // Triggers
  {
    type: 'trigger',
    label: 'Manual Trigger',
    icon: '▶️',
    color: '#00C16E',
    n8nType: 'n8n-nodes-base.manualTrigger',
  },
  {
    type: 'trigger',
    label: 'Webhook',
    icon: '🌐',
    color: '#00C16E',
    n8nType: 'n8n-nodes-base.webhook',
  },
  {
    type: 'trigger',
    label: 'Schedule',
    icon: '⏰',
    color: '#00C16E',
    n8nType: 'n8n-nodes-base.scheduleTrigger',
  },
  
  // AI / LangChain
  {
    type: 'ai',
    label: 'AI Agent',
    icon: '🤖',
    color: '#7B61FF',
    n8nType: '@n8n/n8n-nodes-langchain.agent',
  },
  {
    type: 'ai',
    label: 'OpenAI Chat',
    icon: '💬',
    color: '#7B61FF',
    n8nType: '@n8n/n8n-nodes-langchain.lmChatOpenAi',
  },
  {
    type: 'ai',
    label: 'Memory',
    icon: '🧠',
    color: '#7B61FF',
    n8nType: '@n8n/n8n-nodes-langchain.memoryBufferWindow',
  },
  
  // Communication
  {
    type: 'communication',
    label: 'WhatsApp (Evolution)',
    icon: '📱',
    color: '#00B8D4',
    n8nType: 'n8n-nodes-evolution-api.evolutionApi',
  },
  {
    type: 'communication',
    label: 'Telegram',
    icon: '✈️',
    color: '#00B8D4',
    n8nType: 'n8n-nodes-base.telegram',
  },
  {
    type: 'communication',
    label: 'Send Email',
    icon: '📧',
    color: '#00B8D4',
    n8nType: 'n8n-nodes-base.emailSend',
  },
  
  // Actions
  {
    type: 'action',
    label: 'HTTP Request',
    icon: '🔗',
    color: '#0066FF',
    n8nType: 'n8n-nodes-base.httpRequest',
  },
  {
    type: 'action',
    label: 'Code',
    icon: '💻',
    color: '#0066FF',
    n8nType: 'n8n-nodes-base.code',
  },
  {
    type: 'action',
    label: 'Set',
    icon: '📝',
    color: '#0066FF',
    n8nType: 'n8n-nodes-base.set',
  },
  {
    type: 'action',
    label: 'IF',
    icon: '🔀',
    color: '#0066FF',
    n8nType: 'n8n-nodes-base.if',
  },
  {
    type: 'action',
    label: 'Switch',
    icon: '🔃',
    color: '#0066FF',
    n8nType: 'n8n-nodes-base.switch',
  },
  
  // Database
  {
    type: 'database',
    label: 'PostgreSQL',
    icon: '🐘',
    color: '#FF6D5A',
    n8nType: 'n8n-nodes-base.postgres',
  },
  {
    type: 'database',
    label: 'MySQL',
    icon: '🐬',
    color: '#FF6D5A',
    n8nType: 'n8n-nodes-base.mySql',
  },
];

// Group nodes by category
const groupedNodes = nodeTemplates.reduce((acc, node) => {
  const category = node.type;
  if (!acc[category]) {
    acc[category] = [];
  }
  acc[category].push(node);
  return acc;
}, {} as Record<string, NodeTemplate[]>);

const categoryLabels: Record<string, string> = {
  trigger: '⚡ Triggers',
  ai: '🤖 AI / LangChain',
  communication: '💬 Communication',
  action: '▶️ Actions',
  database: '🗄️ Database',
};

interface ToolPanelProps {
  isOpen: boolean;
  onToggle: () => void;
}

export const ToolPanel = ({ isOpen, onToggle }: ToolPanelProps) => {
  const onDragStart = (event: DragEvent<HTMLDivElement>, template: NodeTemplate) => {
    // Set drag data for the node
    event.dataTransfer.setData('application/reactflow', JSON.stringify({
      type: template.type,
      n8nType: template.n8nType,
      label: template.label,
    }));
    event.dataTransfer.effectAllowed = 'move';
  };

  if (!isOpen) {
    return (
      <button
        onClick={onToggle}
        className="absolute left-4 top-4 z-10 bg-n8n-gray hover:bg-gray-600 text-white p-2 rounded-lg shadow-lg transition-colors"
        title="Open Node Panel"
      >
        <span className="text-xl">➕</span>
      </button>
    );
  }

  return (
    <div className="w-64 bg-n8n-gray border-r border-gray-700 flex flex-col h-full">
      {/* Header */}
      <div className="p-3 border-b border-gray-700 flex items-center justify-between">
        <h3 className="font-semibold text-white text-sm">Add Nodes</h3>
        <button
          onClick={onToggle}
          className="text-gray-400 hover:text-white transition-colors"
        >
          ✕
        </button>
      </div>

      {/* Search */}
      <div className="p-3 border-b border-gray-700">
        <input
          type="text"
          placeholder="Search nodes..."
          className="w-full bg-n8n-dark border border-gray-600 rounded px-3 py-2 text-white text-sm focus:border-blue-500 focus:outline-none"
        />
      </div>

      {/* Node List */}
      <div className="flex-1 overflow-y-auto p-2">
        {Object.entries(groupedNodes).map(([category, nodes]) => (
          <div key={category} className="mb-4">
            <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider px-2 mb-2">
              {categoryLabels[category] || category}
            </h4>
            <div className="space-y-1">
              {nodes.map((template) => (
                <div
                  key={template.n8nType}
                  draggable
                  onDragStart={(e) => onDragStart(e, template)}
                  className="flex items-center gap-2 px-3 py-2 rounded cursor-grab hover:bg-gray-700 transition-colors group"
                  style={{ borderLeft: `3px solid ${template.color}` }}
                >
                  <span className="text-lg">{template.icon}</span>
                  <span className="text-sm text-gray-300 group-hover:text-white">
                    {template.label}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Help */}
      <div className="p-3 border-t border-gray-700 text-xs text-gray-500">
        Drag nodes onto the canvas to add them
      </div>
    </div>
  );
};
