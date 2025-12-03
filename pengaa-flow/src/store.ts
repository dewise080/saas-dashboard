import { create } from 'zustand';
import { applyNodeChanges, applyEdgeChanges, addEdge, Position } from '@xyflow/react';
import type { 
  Connection, 
  EdgeChange, 
  NodeChange, 
  OnConnect, 
  OnEdgesChange, 
  OnNodesChange 
} from '@xyflow/react';
import type { 
  WorkflowNode, 
  WorkflowEdge, 
  N8nWorkflow, 
  WorkflowNodeData 
} from './types';
import dagre from 'dagre';

// Define FlowState interface here to avoid import issues
interface FlowState {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  selectedNode: WorkflowNode | null;
  workflowName: string;
  isDirty: boolean;
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
  onNodesChange: OnNodesChange<WorkflowNode>;
  onEdgesChange: OnEdgesChange<WorkflowEdge>;
  onConnect: OnConnect;
}

const NODE_WIDTH = 220;
const NODE_HEIGHT = 90;

const layoutElements = (
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
  direction: 'LR' | 'TB' = 'LR'
): WorkflowNode[] => {
  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({
    rankdir: direction,
    nodesep: 60,
    ranksep: 120,
    marginx: 40,
    marginy: 40,
  });

  nodes.forEach((node) => {
    const width = Number(node?.width) || NODE_WIDTH;
    const height = Number(node?.height) || NODE_HEIGHT;
    dagreGraph.setNode(node.id, { width, height });
  });

  edges.forEach((edge) => {
    dagreGraph.setEdge(edge.source, edge.target);
  });

  dagre.layout(dagreGraph);

  return nodes.map((node) => {
    const dagreNode = dagreGraph.node(node.id);
    if (!dagreNode) return node;

    const width = Number(node?.width) || NODE_WIDTH;
    const height = Number(node?.height) || NODE_HEIGHT;

    return {
      ...node,
      targetPosition: Position.Left,
      sourcePosition: Position.Right,
      position: {
        x: dagreNode.x - width / 2,
        y: dagreNode.y - height / 2,
      },
    };
  });
};

// Convert n8n workflow to React Flow format
const n8nToReactFlow = (workflow: N8nWorkflow): { nodes: WorkflowNode[]; edges: WorkflowEdge[] } => {
  // Convert nodes
  const nodes: WorkflowNode[] = workflow.nodes.map((n8nNode) => {
    const nodeType = getNodeType(n8nNode.type);
    return {
      id: n8nNode.id,
      type: nodeType,
      position: { x: n8nNode.position[0], y: n8nNode.position[1] },
      data: {
        label: n8nNode.name,
        type: n8nNode.type,
        typeVersion: n8nNode.typeVersion,
        parameters: n8nNode.parameters,
        credentials: n8nNode.credentials,
        nodeType: nodeType,  // For custom node rendering
        n8nNode: n8nNode,
      },
    };
  });

  // Convert connections to edges
  const edges: WorkflowEdge[] = [];
  let edgeIndex = 0;

  for (const [sourceNode, outputs] of Object.entries(workflow.connections)) {
    for (const [outputType, connections] of Object.entries(outputs)) {
      for (const connectionArray of connections) {
        for (const connection of connectionArray) {
          edges.push({
            id: `edge-${edgeIndex++}`,
            source: sourceNode,
            target: connection.node,
            sourceHandle: outputType,
            targetHandle: connection.type,
            type: 'smoothstep',
          });
        }
      }
    }
  }

  return { nodes, edges };
};

// Convert React Flow back to n8n format
const reactFlowToN8n = (
  nodes: WorkflowNode[], 
  edges: WorkflowEdge[], 
  workflowName: string
): N8nWorkflow => {
  // Convert nodes back
  const n8nNodes = nodes.map((node) => ({
    id: node.id,
    name: node.data.label,
    type: node.data.type,
    typeVersion: node.data.typeVersion,
    position: [node.position.x, node.position.y] as [number, number],
    parameters: node.data.parameters,
    credentials: node.data.credentials,
  }));

  // Convert edges back to connections
  const connections: N8nWorkflow['connections'] = {};

  for (const edge of edges) {
    const sourceNode = edge.source;
    const outputType = edge.sourceHandle || 'main';
    const targetNode = edge.target;
    const inputType = edge.targetHandle || 'main';

    if (!connections[sourceNode]) {
      connections[sourceNode] = {};
    }
    if (!connections[sourceNode][outputType]) {
      connections[sourceNode][outputType] = [[]];
    }

    connections[sourceNode][outputType][0].push({
      node: targetNode,
      type: inputType,
      index: 0,
    });
  }

  return {
    name: workflowName,
    nodes: n8nNodes,
    connections,
    active: false,
  };
};

// Map n8n node types to custom React Flow node types
const getNodeType = (n8nType: string): string => {
  const lowerType = n8nType.toLowerCase();
  
  // Trigger nodes
  if (lowerType.includes('trigger') || lowerType.includes('webhook') || lowerType.includes('schedule')) {
    return 'trigger';
  }
  
  // AI/Agent nodes
  if (lowerType.includes('agent') || lowerType.includes('langchain')) {
    return 'agent';
  }
  
  // Tool nodes
  if (lowerType.includes('tool') || lowerType.includes('openai') || lowerType.includes('memory') || lowerType.includes('model')) {
    return 'tool';
  }
  
  return 'default';
};

export const useFlowStore = create<FlowState>((set, get) => ({
  nodes: [],
  edges: [],
  selectedNode: null,
  workflowName: 'Untitled Workflow',
  isDirty: false,

  setNodes: (nodes) => set({ nodes, isDirty: true }),
  
  setEdges: (edges) => set({ edges, isDirty: true }),
  
  addNode: (node) => set((state) => ({ 
    nodes: [...state.nodes, node],
    isDirty: true,
  })),
  
  updateNode: (nodeId, data) => set((state) => ({
    nodes: state.nodes.map((node) =>
      node.id === nodeId
        ? { ...node, data: { ...node.data, ...data } }
        : node
    ),
    isDirty: true,
  })),
  
  removeNode: (nodeId) => set((state) => ({
    nodes: state.nodes.filter((node) => node.id !== nodeId),
    edges: state.edges.filter((edge) => edge.source !== nodeId && edge.target !== nodeId),
    selectedNode: state.selectedNode?.id === nodeId ? null : state.selectedNode,
    isDirty: true,
  })),
  
  setSelectedNode: (nodeId) => set((state) => ({
    selectedNode: nodeId ? state.nodes.find(n => n.id === nodeId) || null : null,
  })),
  
  setWorkflowName: (name) => set({ workflowName: name, isDirty: true }),
  
  importN8nWorkflow: (workflow) => {
    const { nodes, edges } = n8nToReactFlow(workflow);
    const layoutedNodes = layoutElements(nodes, edges);
    set({
      nodes: layoutedNodes,
      edges,
      workflowName: workflow.name,
      selectedNode: null,
      isDirty: false,
    });
  },
  
  exportToN8n: () => {
    const { nodes, edges, workflowName } = get();
    return reactFlowToN8n(nodes, edges, workflowName);
  },
  
  clearWorkflow: () => set({
    nodes: [],
    edges: [],
    selectedNode: null,
    workflowName: 'Untitled Workflow',
    isDirty: false,
  }),

  layoutFlow: (direction = 'LR') => set((state) => ({
    nodes: layoutElements(state.nodes, state.edges, direction),
    isDirty: true,
  })),
  
  // React Flow handlers
  onNodesChange: (changes: NodeChange<WorkflowNode>[]) => {
    set((state) => ({
      nodes: applyNodeChanges<WorkflowNode>(changes, state.nodes),
      isDirty: true,
    }));
  },
  
  onEdgesChange: (changes: EdgeChange<WorkflowEdge>[]) => {
    set((state) => ({
      edges: applyEdgeChanges<WorkflowEdge>(changes, state.edges),
      isDirty: true,
    }));
  },
  
  onConnect: (connection: Connection) => {
    set((state) => ({
      edges: addEdge<WorkflowEdge>({ ...connection, type: 'smoothstep' }, state.edges),
      isDirty: true,
    }));
  },
}));
