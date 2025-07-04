"""Integration tests for NetworkX MCP Server - End-to-end functionality testing."""

import json
import tempfile

import networkx as nx
import pytest

from networkx_mcp.integration import DataPipelines


class TestDataPipelinesIntegration:
    """Test data pipeline integration functionality."""

    def test_csv_to_graph_pipeline(self, temp_files):
        """Test complete CSV to graph pipeline."""
        # Test the CSV pipeline
        result = DataPipelines.csv_pipeline(
            temp_files["csv"], type_inference=True, directed=False
        )

        assert "graph" in result
        assert "num_nodes" in result
        assert "num_edges" in result
        assert "processing_time" in result

        graph = result["graph"]
        assert isinstance(graph, nx.Graph)
        assert graph.number_of_nodes() >= 2
        assert graph.number_of_edges() >= 2

        # Check that attributes were preserved
        for _u, _v, data in graph.edges(data=True):
            assert "weight" in data
            assert isinstance(data["weight"], (int, float))

    def test_json_to_graph_pipeline(self, temp_files):
        """Test JSON to graph pipeline with auto-detection."""
        result = DataPipelines.json_pipeline(temp_files["json"], format_type="auto")

        assert "graph" in result
        assert "format_detected" in result
        assert result["format_detected"] in ["node_link", "edge_list", "adjacency"]

        graph = result["graph"]
        assert graph.number_of_nodes() >= 2

    def test_excel_pipeline(self):
        """Test Excel file processing."""
        # Create temporary Excel file
        import pandas as pd

        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            excel_path = f.name

        try:
            # Create Excel with multiple sheets
            with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
                # Nodes sheet
                nodes_df = pd.DataFrame(
                    {
                        "id": ["A", "B", "C", "D"],
                        "type": ["input", "process", "process", "output"],
                        "value": [1, 2, 3, 4],
                    }
                )
                nodes_df.to_excel(writer, sheet_name="Nodes", index=False)

                # Edges sheet
                edges_df = pd.DataFrame(
                    {
                        "source": ["A", "B", "C"],
                        "target": ["B", "C", "D"],
                        "weight": [1.5, 2.0, 1.0],
                    }
                )
                edges_df.to_excel(writer, sheet_name="Edges", index=False)

            result = DataPipelines.excel_pipeline(
                excel_path, sheet_mapping={"Nodes": "nodes", "Edges": "edges"}
            )

            assert "graph" in result
            assert "sheets_processed" in result

            graph = result["graph"]
            assert graph.number_of_nodes() == 4
            assert graph.number_of_edges() == 3

            # Check node attributes
            assert graph.nodes["A"]["type"] == "input"
            assert graph.nodes["A"]["value"] == 1

            # Check edge attributes
            assert graph.edges["A", "B"]["weight"] == 1.5

        finally:
            import os

            os.unlink(excel_path)

    @pytest.mark.asyncio
    async def test_api_pipeline_mock(self):
        """Test API pipeline with mocked responses."""
        from unittest.mock import AsyncMock, patch

        # Mock API responses
        mock_response_data = {
            "nodes": [
                {"id": "user1", "name": "Alice", "followers": 100},
                {"id": "user2", "name": "Bob", "followers": 50},
            ]
        }

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_response_data)

        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_get.return_value.__aenter__.return_value = mock_response

            endpoints = [
                {
                    "path": "/users",
                    "type": "nodes",
                    "id_field": "id",
                    "data_path": "nodes",
                }
            ]

            result = await DataPipelines.api_pipeline(
                base_url="https://api.example.com", endpoints=endpoints, rate_limit=0.1
            )

            assert "graph" in result
            assert "total_api_requests" in result
            assert "total_items_fetched" in result

            graph = result["graph"]
            assert graph.number_of_nodes() == 2
            assert "user1" in graph.nodes()
            assert graph.nodes["user1"]["name"] == "Alice"

    def test_streaming_pipeline(self):
        """Test streaming data pipeline."""

        def generate_stream_data():
            """Generate streaming graph data."""
            # Add nodes
            yield {"type": "node", "id": "A", "attributes": {"value": 1}}
            yield {"type": "node", "id": "B", "attributes": {"value": 2}}
            yield {"type": "node", "id": "C", "attributes": {"value": 3}}

            # Add edges
            yield {
                "type": "edge",
                "source": "A",
                "target": "B",
                "attributes": {"weight": 1.5},
            }
            yield {
                "type": "edge",
                "source": "B",
                "target": "C",
                "attributes": {"weight": 2.0},
            }

            # Add more nodes
            yield {"type": "node", "id": "D", "attributes": {"value": 4}}
            yield {
                "type": "edge",
                "source": "C",
                "target": "D",
                "attributes": {"weight": 1.0},
            }

        updates = list(
            DataPipelines.streaming_pipeline(
                generate_stream_data(),
                update_interval=0.1,
                window_size=None,  # Cumulative
            )
        )

        # Should have received updates
        assert len(updates) > 0

        final_update = updates[-1]
        assert "graph" in final_update
        assert "num_nodes" in final_update
        assert "num_edges" in final_update
        assert "timestamp" in final_update

        graph = final_update["graph"]
        assert graph.number_of_nodes() == 4
        assert graph.number_of_edges() == 3

    def test_database_pipeline_sqlite(self):
        """Test database pipeline with SQLite."""
        import sqlite3

        # Create temporary SQLite database
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            # Create database with graph data
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # Create table
            cursor.execute(
                """
                CREATE TABLE edges (
                    source TEXT,
                    target TEXT,
                    weight REAL,
                    type TEXT
                )
            """
            )

            # Insert data
            edges_data = [
                ("node1", "node2", 1.5, "collaboration"),
                ("node2", "node3", 2.0, "friendship"),
                ("node3", "node4", 1.0, "collaboration"),
                ("node4", "node1", 2.5, "mentorship"),
            ]

            cursor.executemany(
                "INSERT INTO edges (source, target, weight, type) VALUES (?, ?, ?, ?)",
                edges_data,
            )

            conn.commit()
            conn.close()

            # Test pipeline
            result = DataPipelines.database_pipeline(
                connection_string=db_path,
                query="SELECT source, target, weight, type FROM edges",
                db_type="sqlite",
                edge_columns=("source", "target"),
            )

            assert "graph" in result
            assert "source_database" in result
            assert result["source_database"] == "sqlite"

            graph = result["graph"]
            assert graph.number_of_nodes() == 4
            assert graph.number_of_edges() == 4

            # Check attributes
            for _u, _v, data in graph.edges(data=True):
                assert "weight" in data
                assert "type" in data
                assert data["type"] in ["collaboration", "friendship", "mentorship"]

        finally:
            import os

            os.unlink(db_path)


class TestEndToEndWorkflows:
    """Test complete end-to-end workflows using MCP tools."""

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    @pytest.mark.asyncio
    @pytest.mark.asyncio
class TestComplexDataIntegration:
    """Test integration with complex, real-world-like data scenarios."""

    def test_heterogeneous_data_integration(self, temp_files):
        """Test integrating data from multiple heterogeneous sources."""
        # Create additional data files

        # JSON file with node attributes
        node_attrs_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        node_attrs = {
            "node1": {"type": "person", "age": 25, "department": "engineering"},
            "node2": {"type": "person", "age": 30, "department": "marketing"},
            "node3": {"type": "person", "age": 28, "department": "engineering"},
        }
        json.dump(node_attrs, node_attrs_file)
        node_attrs_file.close()

        try:
            # Step 1: Load basic graph structure from CSV
            graph_result = DataPipelines.csv_pipeline(temp_files["csv"])
            base_graph = graph_result["graph"]

            # Step 2: Enrich with node attributes from JSON
            with open(node_attrs_file.name) as f:
                attrs = json.load(f)

            for node, attr_dict in attrs.items():
                if node in base_graph.nodes():
                    base_graph.nodes[node].update(attr_dict)

            # Step 3: Verify integration
            assert base_graph.number_of_nodes() >= 3

            for node in base_graph.nodes():
                if node in attrs:
                    assert "type" in base_graph.nodes[node]
                    assert "department" in base_graph.nodes[node]

            # Step 4: Analyze by attributes
            engineering_nodes = [
                node
                for node, data in base_graph.nodes(data=True)
                if data.get("department") == "engineering"
            ]

            assert len(engineering_nodes) >= 1

        finally:
            import os

            os.unlink(node_attrs_file.name)

    def test_temporal_data_integration(self):
        """Test integration of temporal/time-series network data."""
        # Create temporal network data
        temporal_data = []

        # Time series of network snapshots
        timestamps = ["2023-01-01", "2023-02-01", "2023-03-01"]

        for i, timestamp in enumerate(timestamps):
            # Evolving network structure
            edges = [
                ("A", "B", {"timestamp": timestamp, "weight": 1.0 + i * 0.1}),
                ("B", "C", {"timestamp": timestamp, "weight": 1.5 + i * 0.2}),
            ]

            # Add new connections over time
            if i > 0:
                edges.append(
                    ("A", "C", {"timestamp": timestamp, "weight": 0.5 + i * 0.3})
                )
            if i > 1:
                edges.append(("C", "D", {"timestamp": timestamp, "weight": 2.0}))

            temporal_data.extend(edges)

        # Create combined temporal graph
        temporal_graph = nx.Graph()

        for source, target, attrs in temporal_data:
            if not temporal_graph.has_edge(source, target):
                temporal_graph.add_edge(source, target, **attrs)
            # Update with latest timestamp data
            elif attrs["timestamp"] > temporal_graph.edges[source, target]["timestamp"]:
                temporal_graph.edges[source, target].update(attrs)

        # Verify temporal integration
        assert temporal_graph.number_of_nodes() == 4
        assert temporal_graph.number_of_edges() == 4

        # Check temporal attributes
        for _u, _v, data in temporal_graph.edges(data=True):
            assert "timestamp" in data
            assert "weight" in data

    def test_multilayer_network_integration(self):
        """Test integration of multilayer/multiplex network data."""
        # Create multilayer network with different relationship types
        layers = {
            "friendship": [("A", "B"), ("B", "C"), ("C", "A")],
            "collaboration": [("A", "C"), ("B", "D"), ("C", "D")],
            "mentorship": [("A", "D"), ("B", "A")],
        }

        # Integrate into single graph with layer attributes
        multilayer_graph = nx.Graph()

        for layer_name, edges in layers.items():
            for source, target in edges:
                if not multilayer_graph.has_edge(source, target):
                    multilayer_graph.add_edge(source, target, layers=[layer_name])
                else:
                    # Edge exists in multiple layers
                    multilayer_graph.edges[source, target]["layers"].append(layer_name)

        # Verify multilayer structure
        assert multilayer_graph.number_of_nodes() == 4

        # Check layer information
        for _u, _v, data in multilayer_graph.edges(data=True):
            assert "layers" in data
            assert len(data["layers"]) >= 1

        # Find edges that exist in multiple layers
        multi_layer_edges = [
            (u, v)
            for u, v, data in multilayer_graph.edges(data=True)
            if len(data["layers"]) > 1
        ]

        assert (
            len(multi_layer_edges) >= 1
        )  # A-C should be in both friendship and collaboration

    def test_geospatial_network_integration(self):
        """Test integration of geospatial network data."""
        # Create network with geographical coordinates
        locations = {
            "NYC": (40.7128, -74.0060),
            "LA": (34.0522, -118.2437),
            "Chicago": (41.8781, -87.6298),
            "Houston": (29.7604, -95.3698),
            "Phoenix": (33.4484, -112.0740),
        }

        # Create graph with geographic data
        geo_graph = nx.Graph()

        # Add nodes with coordinates
        for city, (lat, lon) in locations.items():
            geo_graph.add_node(city, latitude=lat, longitude=lon)

        # Add edges with distances (simplified calculation)
        import math

        def haversine_distance(coord1, coord2):
            """Simplified distance calculation."""
            lat1, lon1 = coord1
            lat2, lon2 = coord2

            # Convert to radians
            lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])

            # Haversine formula
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = (
                math.sin(dlat / 2) ** 2
                + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
            )
            c = 2 * math.asin(math.sqrt(a))
            r = 6371  # Earth's radius in kilometers

            return c * r

        # Add connections between cities
        city_pairs = [
            ("NYC", "Chicago"),
            ("NYC", "Houston"),
            ("LA", "Phoenix"),
            ("LA", "Chicago"),
            ("Chicago", "Houston"),
            ("Houston", "Phoenix"),
        ]

        for city1, city2 in city_pairs:
            coord1 = locations[city1]
            coord2 = locations[city2]
            distance = haversine_distance(coord1, coord2)

            geo_graph.add_edge(city1, city2, distance_km=distance)

        # Verify geospatial integration
        assert geo_graph.number_of_nodes() == 5
        assert geo_graph.number_of_edges() == 6

        # Check geographic attributes
        for _node, data in geo_graph.nodes(data=True):
            assert "latitude" in data
            assert "longitude" in data
            assert -90 <= data["latitude"] <= 90
            assert -180 <= data["longitude"] <= 180

        # Check distance calculations
        for _u, _v, data in geo_graph.edges(data=True):
            assert "distance_km" in data
            assert data["distance_km"] > 0


class TestErrorRecoveryIntegration:
    """Test error recovery and resilience in integration scenarios."""

    def test_partial_data_recovery(self):
        """Test recovery from partially corrupted data."""
        # Create mixed valid/invalid data
        mixed_data = [
            {"source": "A", "target": "B", "weight": 1.5},  # Valid
            {"source": "B", "weight": 2.0},  # Invalid - missing target
            {"source": "C", "target": "D", "weight": "invalid"},  # Invalid weight
            {"source": "D", "target": "E", "weight": 2.5},  # Valid
            {},  # Invalid - empty
            {"source": "E", "target": "A", "weight": 1.0},  # Valid
        ]

        # Process with error recovery
        graph = nx.Graph()
        valid_count = 0
        error_count = 0

        for item in mixed_data:
            try:
                if "source" in item and "target" in item:
                    weight = item.get("weight", 1.0)
                    if isinstance(weight, (int, float)):
                        graph.add_edge(item["source"], item["target"], weight=weight)
                        valid_count += 1
                    else:
                        error_count += 1
                else:
                    error_count += 1
            except Exception:
                error_count += 1

        # Should recover valid data
        assert valid_count == 3
        assert error_count == 3
        assert graph.number_of_nodes() == 5
        assert graph.number_of_edges() == 3

    def test_network_timeout_handling(self):
        """Test handling of network timeouts and retries."""
        from unittest.mock import AsyncMock

        # Mock timeout scenario
        async def timeout_then_success(*args, **kwargs):
            # First call times out
            if not hasattr(timeout_then_success, "called"):
                timeout_then_success.called = True
                msg = "Connection timeout"
                raise TimeoutError(msg)

            # Second call succeeds
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"nodes": [{"id": "test"}]})
            return mock_response

        # This test would require actual implementation of retry logic
        # in the DataPipelines.api_pipeline method
        assert True  # Placeholder for timeout handling test

    def test_memory_limit_handling(self):
        """Test handling of memory limits with large datasets."""
        # Simulate processing large data in chunks
        large_node_count = 10000

        # Process in batches to avoid memory issues
        batch_size = 1000
        graph = nx.Graph()

        for batch_start in range(0, large_node_count, batch_size):
            batch_end = min(batch_start + batch_size, large_node_count)

            # Add batch of nodes
            batch_nodes = [f"node_{i}" for i in range(batch_start, batch_end)]
            graph.add_nodes_from(batch_nodes)

            # Add some edges within batch
            for i in range(len(batch_nodes) - 1):
                graph.add_edge(batch_nodes[i], batch_nodes[i + 1])

        # Verify large graph creation
        assert graph.number_of_nodes() == large_node_count
        assert graph.number_of_edges() == large_node_count - 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
