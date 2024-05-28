from __future__ import annotations
import os
import struct
from typing import Any, List
import zipfile


def read_struct(file, format_: str) -> List[Any]:
    out = struct.unpack(format_, file.read(struct.calcsize(format_)))
    if len(out) == 1:
        return out[0]
    else:
        return out


def read_string(file, offset: int = None) -> str:
    if offset is not None:
        file.seek(offset)
    out = b""
    last_char = b""
    while last_char != b"\x00":
        out = b"".join([out, last_char])
        last_char = file.read(1)
    return out.decode()  # hope it's valid


class MDL:
    """https://developer.valvesoftware.com/wiki/MDL_(Source)"""
    filename: str
    materials: List[str]

    def __init__(self, filename: str):
        self.filename = filename
        self.materials = list()

    def __repr__(self) -> str:
        return f"<MDL '{self.filename}' {len(self.materials)} materials @ 0x{id(self):016X}>"

    @classmethod
    def from_file(cls, path: str) -> MDL:
        out = cls(path)
        with open(path, "rb") as mdl_file:
            assert mdl_file.read(4) == b"IDST", f"'{path}' is not a valid .mdl file"
            version = read_struct(mdl_file, "I")
            if not (48 <= version <= 52):  # TF2 -> Titanfall
                raise NotImplementedError(f".mdl v{version} not supported")
            # skip through the header to textures
            mdl_file.seek(0xCC)  # offsetof(studiohdr_t, num_textures)
            texture_count, texture_offset = read_struct(mdl_file, "2I")
            texture_dir_count, texture_dir_offset = read_struct(mdl_file, "2I")
            if texture_dir_count != 1:
                raise RuntimeError("cannot determine material folder")
            # texture dirs (uint32_t)
            mdl_file.seek(texture_dir_offset)
            texture_dir_offsets = [
                read_struct(mdl_file, "I")
                for i in range(texture_dir_count)]
            texture_dirs = [
                read_string(mdl_file, offset)
                for offset in texture_dir_offsets]
            # textures (mstudiotexture_t)
            mdl_file.seek(texture_offset)
            textures = [
                read_struct(mdl_file, "16I")  # relative name offset, flags etc.
                for i in range(texture_count)]
            # extract .vmt filenames
            for i, texture in enumerate(textures):
                base_offset = texture_offset + (64 * i)
                texture_dir = texture_dirs[0]  # not indexed in the struct (according to VDC)
                texture_name = read_string(mdl_file, base_offset + texture[0])
                out.materials.append(os.path.join("materials", texture_dir, texture_name))
        return out


class VMT:
    """https://developer.valvesoftware.com/wiki/VMT"""
    filename: str
    textures: List[str]

    # NOTE: assuming basetexture2 & blendmodulate aren't in .mdl .vmts
    texture_parameters = [
        "$basetexture",
        "$detail",
        "$bumpmap",
        "%tooltexture"]

    def __init__(self, filename: str):
        self.filename = filename
        self.textures = list()

    def __repr__(self) -> str:
        return f"<VMT '{self.filename}' {len(self.textures)} textures @ 0x{id(self):016X}>"

    @classmethod
    def from_file(cls, path: str) -> VMT:
        out = cls(path)
        with open(path) as vmt_file:
            for line in vmt_file:
                # clean up whitespace and quotes
                line = line.strip().replace('"', "").replace("'", "")
                parameter, _, value = line.partition(" ")
                if parameter in cls.texture_parameters:  # hope it's lowercase
                    out.textures.append(value)
        return out


def split_model_path(path: str) -> str:
    """get the game folder from a model path"""
    path = path.replace("\\", "/").split("/")
    assert "models" in path, "model_path is not a valid mounted folder"
    models_index = path.index("models")
    game_dir = "/".join(path[:models_index])
    model_path = "/".join(path[models_index:])
    return game_dir, model_path


def collect_files(model_path: str) -> (str, List[str]):
    # NOTE: will fail to complete if not all files can be found!
    print("loading .mdl ...")
    mdl = MDL.from_file(model_path)
    print(f"loaded {mdl}")
    game_dir, model_path = split_model_path(model_path)
    file_list = [model_path]
    file_list.extend(vmt + ".vmt" for vmt in mdl.materials)
    print("parsing .vmts ...")
    vmts = [
        VMT.from_file(os.path.join(game_dir, vmt) + ".vmt")
        for vmt in mdl.materials]
    print(f"collecting {sum(len(vmt.textures) for vmt in vmts)} .vtfs ...")
    file_list.extend(
        os.path.join("materials", vtf) + ".vtf"
        for vmt in vmts
        for vtf in vmt.textures)
    print("found all files for this .mdl!")
    return (game_dir, file_list)


def package(*model_paths: str, mod_name: str = "custom_mod"):
    """package up a bunch of models into one .zip"""
    print(f"creating {mod_name}.zip ...")
    zip_contents = list()
    with zipfile.ZipFile(f"{mod_name}.zip", "w") as zip_file:
        for game_dir, copy_list in map(collect_files, model_paths):
            for file_path in copy_list:
                zip_path = os.path.join(mod_name, file_path).replace("\\", "/")
                if zip_path not in zip_contents:
                    zip_file.write(
                        os.path.join(game_dir, file_path),  # full file path
                        os.path.join(mod_name, file_path))  # path in .zip
                    zip_contents.append(zip_path)
    print("Finished!")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print(f"USAGE: {sys.argv[0]} steam/.../models/.../model.mdl ...")
    else:
        package(*sys.argv[1:])
    input("Press ENTER to close this window.")
