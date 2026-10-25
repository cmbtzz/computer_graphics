#version 330 core
layout(location = 0) in vec3 position;
layout(location = 1) in vec3 normal;
layout(location = 2) in vec2 texCoord;
layout(location = 3) in vec3 derivativeU;
layout(location = 4) in vec3 derivativeV;
uniform mat4 viewProjection;
out vec3 worldPosition, surfaceNormal, tangentU, tangentV;
out vec2 uv;
void main() {
    worldPosition = position;
    surfaceNormal = normal;
    tangentU = derivativeU;
    tangentV = derivativeV;
    uv = texCoord;
    gl_Position = viewProjection * vec4(position, 1.0);
}
