import trimesh
import numpy as np
import copy
import threading
import os
import math


pi = math.pi


class UnionThread(threading.Thread):
    def __init__(self, element1, element2):
        threading.Thread.__init__(self)
        self.element1 = element1
        self.element2 = element2
        self.result = None

    def run(self):
        self.result = self.element1.union(self.element2)


class Builder:
    @staticmethod
    def set_facets_color(stl, color):
        facets = stl.facets()
        for facet in facets:
            stl.visual.face_colors[facet] = color

    @staticmethod
    def rotation_matrix(angle, direction, point=None):
        return trimesh.transformations.rotation_matrix(angle, direction, point)

    @staticmethod
    def translation_matrix(matrix):
        return trimesh.transformations.translation_matrix(matrix)

    def __dxf_elements(self, extrude_height=None):
        elements = {}
        for layer in self.layers:
            if layer == '0':
                continue
            E = copy.deepcopy([e for e in self.dxf.entities if e.layer == layer])
            path = trimesh.path.Path2D(entities=E, vertices=self.dxf.vertices.copy())
            if extrude_height is None:
                elements[layer] = path
            else:
                extrude_by = extrude_height
                if layer == self.LAYER_HOLES:
                    extrude_by += 2.0
                extruded = path.extrude(extrude_by)
                if layer == self.LAYER_HOLES:
                    if isinstance(extruded, list):
                        for i in range(len(extruded)):
                            extruded[i].apply_transform(self.translation_matrix([.0, .0, -1.0]))
                    else:
                        extruded.apply_transform(self.translation_matrix([.0, .0, -1.0]))
                        extruded = [extruded]
                elements[layer] = extruded
        return elements

    def __init__(self, dxf_file, source_folder=None, target_folder=None, base_folder=None):
        self.__base_folder = ''
        if base_folder is not None:
            self.__base_folder = base_folder
            if self.__base_folder[-1] != '/':
                self.__base_folder += '/'
        self.__source_folder = self.__base_folder
        if source_folder is not None:
            self.__source_folder += source_folder
            if self.__source_folder[-1] == '/':
                self.__source_folder = self.__source_folder[:-1]
            if not os.path.exists(self.__source_folder):
                raise IOError(2, 'No source directory: \'{}\''.format(self.__source_folder))
        self.__target_folder = self.__base_folder
        if target_folder is not None:
            self.__target_folder += target_folder
            if self.__target_folder[-1] == '/':
                self.__target_folder = self.__target_folder[:-1]
            if not os.path.exists(self.__target_folder):
                raise IOError(2, 'No target directory: \'{}\''.format(self.__target_folder))
        self.__dxf_file = '{}/{}'.format(self.__source_folder, dxf_file)
        if not os.path.isfile(self.__dxf_file):
            raise IOError(2, 'No such file or directory: \'{}\''.format(self.__dxf_file))

        self.dxf = None
        self.layers = None
        self.stl = None

        try:
            self.dxf = trimesh.load(self.__dxf_file)
            self.layers = np.unique(self.dxf.layers)
        except ValueError as e:
            raise BaseException(e, '{}: {}'.format(self.__dxf_file, e))

        self.LAYER_HOLES = 'HOLES'
        self.LAYER_HOLES2 = 'HOLES_PLEXI'
        self.LAYER_CUT = 'CUT'
        self.ENGINE = 'blender'
        self.THREADS = 6
        print('    Source: {}'.format(self.__dxf_file))

    def extrude(self, extrude_height):
        dxf_elements = self.__dxf_elements(extrude_height)
        if dxf_elements is None:
            return
        print('        Layers: {}'.format(dxf_elements.keys()))

        if self.LAYER_CUT not in dxf_elements:
            raise BaseException('Layer \'{}\' was not found!!!'.format(self.LAYER_CUT))

        self.stl = dxf_elements[self.LAYER_CUT]
        if self.LAYER_HOLES2 in dxf_elements:
            if dxf_elements[self.LAYER_HOLES2] != []:
                self.stl = self.stl.difference(dxf_elements[self.LAYER_HOLES2], engine=self.ENGINE)
        if self.LAYER_HOLES in dxf_elements:
            holes_elements = dxf_elements[self.LAYER_HOLES]
            if not isinstance(holes_elements, list):
                holes_elements = [holes_elements]
            while len(holes_elements)>1:
                holes_even = holes_elements[0::2]
                holes_odd = holes_elements[1::2]
                holes_elements = []

                if len(holes_even) > len(holes_odd):
                    holes_elements.append(holes_even[0])
                    del holes_even[0]

                while len(holes_odd) > 0:
                    threads = []
                    for i in range(len(holes_odd)):
                        ut = UnionThread(holes_even[-1], holes_odd[-1])
                        del holes_even[-1]
                        del holes_odd[-1]
                        ut.start()
                        threads.append(ut)
                        if len(threads) == self.THREADS:
                            break

                    for t in threads:
                        t.join()
                        # t.result.show()
                        holes_elements.append(t.result)
            # self.stl.show()
            # holes_elements[0][1].show()
            self.stl = self.stl.difference(holes_elements[0], engine=self.ENGINE)
            # for hole in holes_elements[0]:
            #     self.stl = self.stl.difference(hole, engine=self.ENGINE)
        # self.stl.show()

    def translate(self, matrix):
        self.stl.apply_transform(self.translation_matrix(matrix))

    def rotate(self, instructions):
        if len(instructions) < 2:
            raise BaseException("ERROR", "Need at least 2 items in list for rotation!!!")
        angle, direction, point = eval(str(instructions[0]).lower()), instructions[1], None
        if len(instructions) > 2:
            point = instructions[2]
        self.stl.apply_transform(self.rotation_matrix(angle, direction, point))

    def save(self, stl_file):
        if self.stl is None:
            raise BaseException("ERROR", "No STL data to save!!!")
        stl_file = '{}/{}'.format(self.__target_folder, stl_file)
        print('        Saving: {}'.format(stl_file))
        self.stl.export(stl_file)

    def build(self, yaml_data, stl_file):
        for operations in yaml_data:
            for operation, instructions in operations.items():
                print('        {}: {}'.format(operation, instructions))
                if operation == 'extrude':
                    self.extrude(instructions)
                if operation == 'translate':
                    self.translate(instructions)
                if operation == 'rotate':
                    if isinstance(instructions[0], list):
                        for instruction in instructions:
                            self.rotate(instruction)
                    else:
                        self.rotate(instructions)
        self.save(stl_file)
