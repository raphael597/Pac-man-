import random

class Koordinaten:
    dim = 2

    def __init__(self,x:int,y:int):
        if not isinstance(x,int) or not isinstance(y,int):
            raise TypeError(f"Integerkoordinaten erwartet, {x},{y} bekommen.")
        self._x = x
        self._y = y

    def __eq__(self, other):
        if not isinstance(other, Koordinaten):
            return NotImplemented
        return self._x == other._x and self._y == other._y

    def __hash__(self):
        return hash((self._x, self._y))
        
    def __str__(self):
        return f"Koordinaten: {self._x}, {self._y}"
    
    def __repr__(self):
        return str(self)

    def __add__(self, other):
        return Koordinaten(self._x+other._x,self._y+other._y)
    
    def __sub__(self, other):
        return Koordinaten(self._x-other._x,self._y-other._y)
    
    def __iadd__(self, other):
        self._x += other._x
        self._y += other._y
        return self

    def __isub__(self, other):
        self._x -= other._x
        self._y -= other._y
        return self

    def distance(self,other):
        return abs(self._x-other._x)+abs(self._y-other._y)


class Direction(Koordinaten):
    west = Koordinaten(-1,0)
    east = Koordinaten(1,0)
    north = Koordinaten(0,-1)
    south = Koordinaten(0,1)

    def __str__(self):
        return f"Direction: {self._x}, {self._y}"
    
    def __repr__(self):
        return str(self)

class Position(Koordinaten):
    fieldsize = 20

    def __init__(self,x:int,y:int):
        super().__init__(x,y)
        self._PeriodicBoundary()

    def __str__(self):
        return f"Position: {self._x}, {self._y}"
    
    def __repr__(self):
        return str(self)

    def _PeriodicBoundary(self):
        while self._x < 0:
            self._x += Position.fieldsize
        self._x = self._x % Position.fieldsize
        while self._y < 0:
            self._y += Position.fieldsize
        self._y = self._y % Position.fieldsize

    def __add__(self, other):
        return Position(self._x+other._x,self._y+other._y)
        
    def __sub__(self, other):
        return Position(self._x-other._x,self._y-other._y)

    def __iadd__(self, other):
        super().__iadd__(other)
        self._PeriodicBoundary()
        return self

    def __isub__(self, other):
        super().__isub__(other)
        self._PeriodicBoundary()
        return self

class FieldEntry:
    def __init__(self,p):
        self.position = p
        self.logo = " "
        self.icon = "icons/Empty.png"

    def __str__(self):
        return self.logo
    
    def __repr__(self):
        return str(self)

class Empty(FieldEntry):
    def __init__(self,p):
        super().__init__(p)

class Wall(FieldEntry):
    def __init__(self,p):
        super().__init__(p)
        self.logo = "X"
        self.icon = "icons/Wall.png"

class Cabbage(FieldEntry):
    def __init__(self,p):
        super().__init__(p)
        self.strength = 1
        self.logo = "."
        self.icon = "icons/Cabbage.png"

class Pacman(FieldEntry):
    def __init__(self,p,name,field):
        super().__init__(p)
        self.strength = 1
        self.logo = "P"
        self.icon = "icons/Pacman.png"
        self.name = name
        self.direction = Direction.east
        self._field = field
        self.alive = True

    def _Move(self):
        newPos = self.position + self.direction
        fieldentry = self._field[newPos]
        if isinstance(fieldentry, Wall):
            return
        if isinstance(fieldentry, Empty):
            self._DoMove(newPos)
        elif isinstance(fieldentry, Cabbage):
            self.strength += fieldentry.strength
            self._DoMove(newPos)
        elif isinstance(fieldentry, Pacman):
            a = self.strength
            z = self.direction + fieldentry.direction
            if z._x==0 and z._y==0:
                b = fieldentry.strength
            elif abs(z._x)==1 and abs(z._y)==1:
                b = fieldentry.strength/5.0
            else :
                b = fieldentry.strength/10.0
            
            if random.random() < a/(a+b):
                self.strength += fieldentry.strength
                self._DoMove(newPos)
                fieldentry.alive = False
            else:
                fieldentry.strength += self.strength
                self.alive = False
                del self._field[self.position]
                self._field[self.position] = Empty(self.position)
            
    def _DoMove(self,newPos):
        oldPos = self.position
        del self._field[oldPos]
        del self._field[newPos]
        self.position = newPos
        self._field[oldPos] = Empty(oldPos)
        self._field[newPos] = self
        
    def TurnOrMoveOrStill(self):
        action = random.choice(range(2))
        if action == 0:
            self.direction = random.choice([Direction.west,Direction.east,Direction.north,Direction.south])
        elif action == 1:
            self._Move()
        
class Field:
    def __init__(self, fieldsize: int, pacmanlist:list, walls: list):
        Position.fieldsize = fieldsize
        self._freefields = []
        self.field = {}
        for x in range(fieldsize):
            for y in range(fieldsize):
                pos = Position(x,y)
                cabbage = Cabbage(pos)
                self.field[pos] = cabbage
                self._freefields.append(pos)

        for pos, direction, length in walls:
            self.buildWall(pos, direction, length)
            
            
        self.pacmans = []
        for cls,name in pacmanlist:
            pos = random.choice(self._freefields)
            del self.field[pos]
            pacman = cls(pos, name, self.field)
            self.field[pos] = pacman
            self.pacmans.append(pacman)
            self._freefields.remove(pos)
            
    def __str__(self):
        fstr = ""
        for y in range(Position.fieldsize):
            for x in range(Position.fieldsize):
                pos = Position(x,y)
                fstr += str(self.field[pos])
            fstr += "\n"
        for pacman in self.pacmans:
            fstr += f"{pacman.name}: {pacman.strength} "
        fstr += "\n"
        return fstr

    def buildWall(self, pos, direction, length):
        p = Position(pos[0], pos[1])
        for _ in range(length):
            del self.field[p]
            wall = Wall(p)
            self.field[p] = wall
            self._freefields.remove(p)
            p = p + direction
    
    def __repr__(self):
        return str(self)
