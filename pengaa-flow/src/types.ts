// Types imported where needed from @xyflow/react

// n8n workflow JSON types
export interface N8nNode {
  id: string;
  name: string;
  type: string;
  typeVersion: number;
  position: [number, number];
  parameters: Record<string, unknown>;
  credentials?: Record<string, { id: string; name: string }>;
}

export interface N8nConnection {
  node: string;
  type: string;
  index: number;
}

export interface N8nConnections {
  [sourceNode: string]: {
    [outputType: string]: N8nConnection[][];
  };
}

export interface N8nWorkflow {
  id?: string;
  name: string;
  nodes: N8nNode[];
  connections: N8nConnections;
  active: boolean;
  settings?: Record<string, unknown>;
  tags?: string[];
}

// React Flow node data
export interface WorkflowNodeData {
  label: string;
  type: string;
  typeVersion: number;
  parameters: Record<string, unknown>;
  credentials?: Record<string, { id: string; name: string }>;
  nodeType?: string;  // For custom node rendering (trigger, agent, tool, etc.)
  // Original n8n node reference
  n8nNode: N8nNode;
  [key: string]: unknown;  // Allow additional properties
}

// Custom node types - define as interfaces to avoid type-only export issues
export interface WorkflowNode {
  id: string;
  type?: string;
  position: { x: number; y: number };
  data: WorkflowNodeData;
  selected?: boolean;
  dragging?: boolean;
  [key: string]: unknown;
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
  type?: string;
  animated?: boolean;
  style?: Record<string, unknown>;
  [key: string]: unknown;
}

// Node categories
export type NodeCategory = 
  | 'trigger'
  | 'action'
  | 'ai'
  | 'data'
  | 'flow'
  | 'communication'
  | 'utility';

// Node type metadata
export interface NodeTypeMeta {
  type: string;
  category: NodeCategory;
  color: string;
  icon: string;
  displayName: string;
}

// Credential types
export interface Credential {
  id: string;
  name: string;
  type: string;
  createdAt: string;
  updatedAt: string;
}

// Store state
export interface FlowState {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  selectedNode: WorkflowNode | null;
  workflowName: string;
  isDirty: boolean;
  
  // Actions
  setNodes: (nodes: WorkflowNode[]) => void;
  setEdges: (edges: WorkflowEdge[]) => void;
  addNode: (node: WorkflowNode) => void;
  updateNode: (nodeId: string, data: Partial<WorkflowNodeData>) => void;
  removeNode: (nodeId: string) => void;
  setSelectedNode: (nodeId: string | null) => void;
  setWorkflowName: (name: string) => void;
  importN8nWorkflow: (workflow: N8nWorkflow) => void;
  exportToN8n: () => N8nWorkflow;
  clearWorkflow: () => void;
  layoutFlow: (direction?: 'LR' | 'TB') => void;
  
  // React Flow handlers
  onNodesChange: (changes: any) => void;
  onEdgesChange: (changes: any) => void;
  onConnect: (connection: any) => void;
}
