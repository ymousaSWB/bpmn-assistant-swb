<template>
  <div style="display: flex; flex-direction: row; height: 100vh">
    <div class="chat-container">
      <ChatInterface
        @bpmn-xml-received="handleBpmnXml"
        @bpmn-json-received="setBpmnJson"
        @download="downloadBpmnFile"
        :isDownloadReady="!!bpmnXml"
        :process="process"
      />
    </div>

    <div class="canvas-wrapper">
      <div class="bpmn-toolbar">
        <button @click="undoBpmn">Undo</button>
        <button @click="redoBpmn">Redo</button>

        <label class="toolbar-button">
          Import BPMN
          <input
            type="file"
            accept=".bpmn,.xml"
            @change="importBpmnFile"
            hidden
          />
        </label>

        <button @click="downloadBpmnFile">Export BPMN</button>
        <button @click="exportSvg">Export SVG</button>
      </div>

      <div
        id="canvas"
        class="canvas-container"
        @dragover.prevent
        @drop="handleDrop"
      ></div>
    </div>

    <v-snackbar v-model="snackbar.show" :color="snackbar.color" :timeout="3000">
      {{ snackbar.text }}
    </v-snackbar>
  </div>
</template>

<script>
import BpmnModeler from 'bpmn-js/lib/Modeler';
import ChatInterface from '../components/ChatInterface.vue';
import { bpmnAssistantUrl, bpmnLayoutServerUrl } from '../config';
import { getApiKeys } from '../utils/apiKeys';
// import initialDiagram from "../assets/initialDiagram.js";
import 'bpmn-js/dist/assets/diagram-js.css';
import 'bpmn-js/dist/assets/bpmn-js.css';
import 'bpmn-js/dist/assets/bpmn-font/css/bpmn-embedded.css';

export default {
  name: 'App',
  components: {
    ChatInterface,
  },
  data() {
    return {
      bpmnXml: '',
      process: null,
      bpmnViewer: null,
      snackbar: {
        show: false,
        text: '',
        color: 'success',
      },
    };
  },
  mounted() {
    this.bpmnViewer = new BpmnModeler({
      container: '#canvas',
    });

    // this.bpmnViewer
    //   .importXML(initialDiagram)
    //   .then((result) => {
    //     const { warnings } = result;
    //     console.log("BPMN diagram imported successfully", warnings);
    //     this.bpmnViewer.get("canvas").zoom("fit-viewport");
    //   })
    //   .catch((err) => {
    //     console.error("Failed to import BPMN diagram:", err);
    //   });
  },
  beforeUnmount() {
    if (this.bpmnViewer) {
      this.bpmnViewer.destroy();
    }
  },
  methods: {
    showSnackbar(text, color = 'success') {
      this.snackbar.text = text;
      this.snackbar.color = color;
      this.snackbar.show = true;
    },

    undoBpmn() {
      if (!this.bpmnViewer) return;
      this.bpmnViewer.get('commandStack').undo();
    },

    redoBpmn() {
      if (!this.bpmnViewer) return;
      this.bpmnViewer.get('commandStack').redo();
    },

    async importBpmnFile(event) {
      const file = event.target.files?.[0];
      if (!file || !this.bpmnViewer) return;

      try {
        const xmlContent = await file.text();

        await this.bpmnViewer.importXML(xmlContent);
        this.bpmnViewer.get('canvas').zoom('fit-viewport');

        this.bpmnXml = xmlContent;
        await this.createBpmnJson();

        this.showSnackbar('BPMN file imported successfully', 'success');
      } catch (err) {
        console.error('Failed to import BPMN file:', err);
        this.showSnackbar('Failed to import BPMN file', 'error');
      } finally {
        event.target.value = '';
      }
    },

    async exportSvg() {
      if (!this.bpmnViewer) return;

      try {
        const { svg } = await this.bpmnViewer.saveSVG();
        const blob = new Blob([svg], { type: 'image/svg+xml' });
        const url = window.URL.createObjectURL(blob);

        const a = document.createElement('a');
        a.href = url;
        a.download = 'diagram.svg';
        a.click();

        window.URL.revokeObjectURL(url);
      } catch (err) {
        console.error('Failed to export SVG:', err);
        this.showSnackbar('Failed to export SVG', 'error');
      }
    },

    async handleDrop(event) {
      event.preventDefault();

      if (event.dataTransfer.items) {
        for (let i = 0; i < event.dataTransfer.items.length; i++) {
          if (event.dataTransfer.items[i].kind === 'file') {
            const file = event.dataTransfer.items[i].getAsFile();

            if (file.name.endsWith('.bpmn') || file.name.endsWith('.xml')) {
              const reader = new FileReader();

              reader.onload = async (e) => {
                const xmlContent = e.target.result;

                try {
                  await this.bpmnViewer.importXML(xmlContent);
                  this.bpmnViewer.get('canvas').zoom('fit-viewport');

                  console.log('BPMN diagram loaded successfully');

                  this.bpmnXml = xmlContent;
                  await this.createBpmnJson();

                  this.showSnackbar('BPMN file imported successfully', 'success');
                } catch (err) {
                  console.error('Failed to import BPMN diagram:', err);
                  this.showSnackbar('Failed to import BPMN file', 'error');
                }
              };

              reader.readAsText(file);
            }
          }
        }
      }
    },

    async createBpmnJson() {
      try {
        const apiKeys = getApiKeys();

        const response = await fetch(`${bpmnAssistantUrl}/bpmn_to_json`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ bpmn_xml: this.bpmnXml, api_keys: apiKeys }),
        });

        if (!response.ok) {
          throw new Error(`HTTP error! Status: ${response.status}`);
        }

        this.process = await response.json();

        console.log('BPMN JSON created successfully:', this.process);
        this.showSnackbar('BPMN successfully uploaded', 'success');
      } catch (error) {
        console.error('Error creating BPMN JSON:', error);
        this.showSnackbar(
          'There was a problem while loading the BPMN file',
          'error'
        );
      }
    },

    async handleBpmnXml(bpmnXmlValue) {
      if (bpmnXmlValue === '') {
        if (this.bpmnViewer) {
          this.bpmnViewer.destroy();
        }

        this.bpmnViewer = new BpmnModeler({
          container: '#canvas',
        });

        this.bpmnXml = '';
        this.process = null;

        return;
      }

      try {
        const layoutedXml = await this.processDiagram(bpmnXmlValue);

        if (!layoutedXml) {
          throw new Error('Failed to layout the BPMN diagram');
        }

        this.bpmnXml = layoutedXml;

        if (this.bpmnViewer) {
          this.bpmnViewer
            .importXML(layoutedXml)
            .then((result) => {
              const { warnings } = result;
              console.log('BPMN diagram imported successfully', warnings);
              this.bpmnViewer.get('canvas').zoom('fit-viewport');
            })
            .catch((err) => {
              console.error('Failed to import BPMN diagram:', err);
            });
        }
      } catch (error) {
        console.error('Error handling BPMN XML:', error);
      }
    },

    async processDiagram(bpmnDiagram) {
      try {
        const response = await fetch(`${bpmnLayoutServerUrl}/process-bpmn`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ bpmnXml: bpmnDiagram }),
        });

        if (!response.ok) {
          throw new Error('Network response was not ok');
        }

        const { layoutedXml } = await response.json();

        console.log(layoutedXml);

        return layoutedXml;
      } catch (error) {
        console.error('Failed to process the diagram:', error);
      }
    },

    async downloadBpmnFile() {
      if (!this.bpmnViewer) return;

      try {
        const { xml } = await this.bpmnViewer.saveXML({ format: true });
        const blob = new Blob([xml], { type: 'application/xml' });
        const url = window.URL.createObjectURL(blob);

        const a = document.createElement('a');
        a.href = url;
        a.download = 'diagram.bpmn';
        a.click();

        window.URL.revokeObjectURL(url);
      } catch (err) {
        console.error('Failed to export BPMN:', err);
        this.showSnackbar('Failed to export BPMN', 'error');
      }
    },

    setBpmnJson(value) {
      this.process = value;
    },
  },
};
</script>

<style>
.chat-container {
  flex: 3;
}

.canvas-wrapper {
  flex: 4;
  display: flex;
  flex-direction: column;
  margin: 10px;
  border: 2px solid gray;
}

.bpmn-toolbar {
  display: flex;
  gap: 8px;
  padding: 8px;
  border-bottom: 1px solid #ddd;
  background: #fafafa;
  align-items: center;
  flex-wrap: wrap;
}

.bpmn-toolbar button,
.toolbar-button {
  border: 1px solid #ccc;
  background: white;
  padding: 6px 10px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  font-family: inherit;
}

.bpmn-toolbar button:hover,
.toolbar-button:hover {
  background: #f0f0f0;
}

.canvas-container {
  flex: 1;
}

@media (min-width: 1800px) {
  .chat-container {
    flex: 2;
  }

  .canvas-wrapper {
    flex: 5;
  }
}
</style>
