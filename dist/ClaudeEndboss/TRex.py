from Pacman import Position, Direction, Pacman

class TRex(Pacman):
    def __init__(self,p,name,field):
        super().__init__(p,name,field)
        self.logo = "T"
        self.icon = "icons/TRex.png"
        self.step_count = 0
        
    def TurnOrMoveOrStill(self):
        self.step_count += 1
        if self.step_count == 1:
            self.direction = Direction.south
        elif self.step_count == 3:
            self.direction = Direction.east
        else: 
            self._Move()
        if self.step_count == Position.fieldsize+2:
            self.step_count = 0

